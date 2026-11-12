import argparse
import csv
import os
import sys
import time
from pathlib import Path

import pendulum
import requests

from orchestrate.utils.storage import object_exists, put_json_gz, put_text

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MODEL = "era5"
# Massimo 10 variabili: oltre, ogni richiesta pesa di piu' sul limite di chiamate
HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "cloud_cover",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "direct_normal_irradiance",
    "sunshine_duration",
)
SOURCE = "weather_hourly"
LOCAL_TZ = "Europe/Rome"
CHUNK_SIZE = 100
# Un blocco da 100 punti per un mese vale circa 220 chiamate: con 30 secondi di pausa
# si resta sotto il limite di 600 chiamate al minuto
PAUSE_BETWEEN_CALLS_SECONDS = 30
COORDINATE_TOLERANCE = 0.01

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GRID_FILE = PROJECT_ROOT / "seeds" / "grid_points.csv"


class DailyLimitReached(RuntimeError):
    """L'API ha segnalato il superamento del limite giornaliero di chiamate."""


def load_grid(limit: int | None = None) -> list[dict]:
    """Punti della griglia da seeds/grid_points.csv; limit serve solo per prove e CI."""
    with open(GRID_FILE, newline="", encoding="utf-8") as handle:
        points = [
            {"grid_id": row["grid_id"], "latitude": float(row["latitude"]), "longitude": float(row["longitude"])}
            for row in csv.DictReader(handle)
        ]
    if not points:
        raise ValueError(f"nessun punto in {GRID_FILE}")
    return points[:limit] if limit else points


def _parse_month(month: str) -> pendulum.DateTime:
    return pendulum.from_format(month, "YYYY-MM", tz="UTC").start_of("month")


def previous_month() -> str:
    return pendulum.now(LOCAL_TZ).start_of("month").subtract(months=1).format("YYYY-MM")


def resolve_months(month: str | None = None, start_month: str | None = None, end_month: str | None = None) -> list[str]:
    """Mesi da estrarre: uno solo (month, default il mese precedente) oppure un intervallo
    (da start_month a end_month compresi, end_month default il mese precedente).
    Sono ammessi solo mesi gia' conclusi."""
    last_complete = previous_month()
    if start_month:
        if month:
            raise ValueError("indicare 'month' oppure 'start_month'/'end_month', non entrambi")
        first, last = _parse_month(start_month), _parse_month(end_month or last_complete)
        if first > last:
            raise ValueError(f"intervallo di mesi vuoto: {start_month} > {end_month or last_complete}")
        months, current = [], first
        while current <= last:
            months.append(current.format("YYYY-MM"))
            current = current.add(months=1)
    else:
        if end_month:
            raise ValueError("'end_month' richiede 'start_month'")
        months = [_parse_month(month).format("YYYY-MM") if month else last_complete]

    not_complete = [m for m in months if m > last_complete]
    if not_complete:
        raise ValueError(f"mesi non ancora conclusi: {not_complete}; ultimo mese ammesso {last_complete}")
    return months


def _get_json(url: str, params: dict, retries: int = 4):
    """GET con tentativi su errori temporanei (5xx, rete) e gestione dei limiti di chiamate (429):
    limite al minuto od orario -> attesa e nuovo tentativo; limite giornaliero -> DailyLimitReached."""
    last_error = None
    attempt = 0
    while attempt < retries:
        attempt += 1
        try:
            response = requests.get(url, params=params, timeout=120)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2 ** attempt)
            continue

        if response.status_code == 429:
            try:
                reason = str(response.json().get("reason", ""))
            except ValueError:
                reason = response.text[:200]
            lowered = reason.lower()
            if "daily" in lowered:
                raise DailyLimitReached(reason)
            if "hourly" in lowered:
                now = pendulum.now("UTC")
                wait = (now.start_of("hour").add(hours=1) - now).total_seconds() + 30
            else:
                wait = 65
            print(f"[{SOURCE}] limite di chiamate ({reason or 'HTTP 429'}): attendo {int(wait)} secondi")
            time.sleep(wait)
            attempt -= 1  # l'attesa per il limite non consuma un tentativo
            continue

        if response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            time.sleep(2 ** attempt)
            continue

        if response.status_code >= 400:
            # errore della richiesta: riprovare non serve
            raise RuntimeError(f"richiesta rifiutata (HTTP {response.status_code}): {response.text[:300]}")

        try:
            return response.json()
        except ValueError as exc:
            last_error = exc
            time.sleep(2 ** attempt)

    raise RuntimeError(f"chiamata a {url} fallita dopo {retries} tentativi: {last_error}")


def month_is_complete(target: str, month: str) -> bool:
    return object_exists(target, f"landing/{SOURCE}/month={month}/_SUCCESS")


def extract_month(target: str, month: str, grid: list[dict]) -> int:
    """Scarica un mese per tutti i punti della griglia. Restituisce il numero di file scritti."""
    first_day = _parse_month(month)
    start_date = first_day.to_date_string()
    end_date = first_day.end_of("month").to_date_string()
    chunks = [grid[i:i + CHUNK_SIZE] for i in range(0, len(grid), CHUNK_SIZE)]

    for index, chunk in enumerate(chunks):
        if index:
            time.sleep(PAUSE_BETWEEN_CALLS_SECONDS)
        params = {
            "latitude": ",".join(f"{p['latitude']:.2f}" for p in chunk),
            "longitude": ",".join(f"{p['longitude']:.2f}" for p in chunk),
            "start_date": start_date,
            "end_date": end_date,
            "hourly": ",".join(HOURLY_VARIABLES),
            "models": MODEL,
            "timezone": "GMT",
            # 'nearest': la cella della griglia piu' vicina al punto, senza spostarsi su una cella di terra
            "cell_selection": "nearest",
        }
        payload = _get_json(ARCHIVE_URL, params)
        locations = payload if isinstance(payload, list) else [payload]
        if len(locations) != len(chunk):
            raise RuntimeError(f"mese {month}, blocco {index}: attesi {len(chunk)} punti, ricevuti {len(locations)}")

        records = []
        for point, location in zip(chunk, locations):
            if (abs(location["latitude"] - point["latitude"]) > COORDINATE_TOLERANCE
                    or abs(location["longitude"] - point["longitude"]) > COORDINATE_TOLERANCE):
                raise RuntimeError(
                    f"mese {month}, punto {point['grid_id']}: l'API ha risposto per "
                    f"({location['latitude']}, {location['longitude']})"
                )
            records.append({"grid_id": point["grid_id"], **location})

        path = put_json_gz(target, f"landing/{SOURCE}/month={month}/part-{index:03d}.json.gz", records)
        print(f"[{SOURCE}] {month} blocco {index + 1}/{len(chunks)} ({len(chunk)} punti) -> {path}")

    put_text(target, f"landing/{SOURCE}/month={month}/_SUCCESS", pendulum.now("UTC").to_iso8601_string())
    return len(chunks)


def extract(
    target: str,
    months: list[str],
    skip_existing: bool = False,
    limit_points: int | None = None,
    max_months: int | None = None,
) -> tuple[list[str], bool]:
    """Estrae i mesi indicati, in ordine. Restituisce (mesi estratti in questa esecuzione,
    True se ci si e' fermati per il limite giornaliero dell'API).

    skip_existing: salta i mesi gia' completi nel landing (per il backfill).
    max_months: numero massimo di mesi da estrarre in questa esecuzione.
    """
    grid = load_grid(limit_points)
    done = []
    for month in months:
        if max_months is not None and len(done) >= max_months:
            break
        if skip_existing and month_is_complete(target, month):
            print(f"[{SOURCE}] {month} gia' presente nel landing, salto")
            continue
        if done:
            time.sleep(PAUSE_BETWEEN_CALLS_SECONDS)
        try:
            extract_month(target, month, grid)
        except DailyLimitReached as exc:
            print(f"[{SOURCE}] limite giornaliero dell'API raggiunto durante {month}: {exc}", file=sys.stderr)
            return done, True
        done.append(month)
    return done, False


def main():
    # da riga di comando in locale le credenziali stanno nel file .env del progetto;
    # le variabili gia' presenti nell'ambiente (Prefect, CI) non vengono sovrascritte.
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Estrae i dati meteo orari nel landing su Tigris")
    parser.add_argument("--target", choices=["dev", "prd"], default=os.getenv("DBT_TARGET", "dev"))
    parser.add_argument("--month", help="mese da estrarre (YYYY-MM); default il mese precedente")
    parser.add_argument("--start-month", help="backfill: primo mese (YYYY-MM)")
    parser.add_argument("--end-month", help="backfill: ultimo mese (YYYY-MM); default il mese precedente")
    parser.add_argument("--max-months", type=int, help="backfill: numero massimo di mesi per esecuzione")
    parser.add_argument("--force", action="store_true", help="backfill: riscarica anche i mesi gia' completi")
    parser.add_argument("--limit-points", type=int, help="solo i primi N punti della griglia (prove e CI)")
    args = parser.parse_args()

    months = resolve_months(args.month, args.start_month, args.end_month)
    backfill = bool(args.start_month)
    done, limit_reached = extract(
        args.target,
        months,
        skip_existing=backfill and not args.force,
        limit_points=args.limit_points,
        max_months=args.max_months,
    )
    print(f"[{SOURCE}] mesi estratti: {', '.join(done) if done else 'nessuno'}")
    if limit_reached:
        print(f"[{SOURCE}] interrotto per il limite giornaliero: rilanciare lo stesso comando domani", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
