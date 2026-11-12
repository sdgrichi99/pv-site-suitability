import json
import os
import sys
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional

# risolve la root del progetto (la cartella genitore rispetto a /orchestrate)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# la root va aggiunta a sys.path PRIMA di importare 'orchestrate' e 'ducklake_plugin':
# con prefect managed il progetto viene clonato in una cartella temporanea.
sys.path.append(str(PROJECT_ROOT))

import boto3
from prefect import flow, task, get_run_logger
from orchestrate.extract import weather
from orchestrate.utils.notifications import notify_on_failure, notify_on_success

VALID_TARGETS = ("dev", "prd")

# numero di mesi riportati nella mail
REPORT_MONTHS = 10
# righe del registro audit.model_load_log (scritto dal post-hook log_model_rows, vedi
# macros/model_load_log.sql) da riportare nella mail: per ogni tabella di bronze, l'ultimo
# caricamento di ciascuno degli ultimi REPORT_MONTHS mesi.
LOAD_LOG_QUERY = """
select
    model_name,
    schema_name,
    cast(load_date as varchar) as load_date,
    month_key,
    rows_inserted,
    strftime(logged_at, '%Y-%m-%d %H:%M:%S') as logged_at
from (
    select *, dense_rank() over (order by month_key desc) as month_rank
    from (
        select *
        from lakehouse_{target}.audit.model_load_log
        where schema_name = 'bronze'
        qualify row_number() over (partition by model_name, month_key order by logged_at desc) = 1
    )
)
where month_rank <= {months}
order by model_name, month_key
"""


def get_target() -> str:
    # legge dbt_target (default dev) e lo valida: ammessi solo 'dev' e 'prd'.
    target = os.getenv("DBT_TARGET", "dev").strip().lower()
    if target not in VALID_TARGETS:
        raise ValueError(f"DBT_TARGET deve essere uno tra {VALID_TARGETS}, ricevuto '{target}'")
    return target


def cleanup_tigris_tmp(target: str):
    # elimina tutti i prefissi e file temporanei __dbt_tmp da tigris s3.
    # in ducklake le tabelle vive risiedono in cartelle '<tabella>__dbt_tmp/',
    suffix = target.upper()  # dev | prd, stesso suffisso usato da ducklake_plugin
    raw_bucket = os.getenv(f"TIGRIS_BUCKET_{suffix}", "")

    bucket_name = raw_bucket.replace("s3://", "").strip("/")
    if not bucket_name:
        print(f"[CLEANUP] TIGRIS_BUCKET_{suffix} non configurato, salto la pulizia.")
        return

    # stesse variabili usate da profiles.yml per il target corrispondente
    if target == "prd":
        raw_endpoint = os.getenv("AWS_ENDPOINT_URL_S3_PRD", "")
        key_id = os.getenv("AWS_ACCESS_KEY_ID_PRD")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY_PRD")
    else:
        raw_endpoint = os.getenv("AWS_ENDPOINT_URL_S3", "")
        key_id = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

    # normalizza l'endpoint per boto3
    if raw_endpoint and not raw_endpoint.startswith("http"):
        endpoint_url = f"https://{raw_endpoint}"
    else:
        endpoint_url = raw_endpoint or "https://fly.storage.tigris.dev"

    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=key_id,
            aws_secret_access_key=secret_key,
            region_name="auto"
        )

        paginator = s3.get_paginator("list_objects_v2")
        deleted_count = 0

        for page in paginator.paginate(Bucket=bucket_name):
            if "Contents" in page:
                keys_to_delete = [
                    {"Key": item["Key"]}
                    for item in page["Contents"]
                    if "__dbt_tmp" in item["Key"]
                ]
                if keys_to_delete:
                    s3.delete_objects(
                        Bucket=bucket_name,
                        Delete={"Objects": keys_to_delete}
                    )
                    deleted_count += len(keys_to_delete)

        if deleted_count > 0:
            print(f"[CLEANUP] Rimossi {deleted_count} oggetti temporanei da {bucket_name}.")
        else:
            print("[CLEANUP] Nessun oggetto __dbt_tmp trovato su Tigris.")

    except Exception as e:
        print(f"[CLEANUP WARNING] Errore durante la rimozione dei file temporanei: {e}", file=sys.stderr)


@task(name="Estrai dati meteo", retries=1, retry_delay_seconds=300)
def extract_weather(target: str, months: List[str], skip_existing: bool = False, max_months: Optional[int] = None):
    # scarica i mesi indicati dall'api e li scrive nel landing su tigris.
    # restituisce (mesi estratti, True se fermato dal limite giornaliero dell'api).
    logger = get_run_logger()
    done, limit_reached = weather.extract(target, months, skip_existing=skip_existing, max_months=max_months)
    logger.info(f"mesi scritti nel landing ({target}): {', '.join(done) if done else 'nessuno'}")
    if limit_reached:
        logger.warning("limite giornaliero dell'api raggiunto: rilanciare il flow domani per i mesi restanti")
    return done, limit_reached


@task(name="Esegui Pipeline dbt")
def run_dbt(select: Optional[str] = None, months: Optional[List[str]] = None, full_refresh: bool = False):
    logger = get_run_logger()
    target = get_target()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["DBT_TARGET"] = target

    command = [
        "dbt", "build",
        "--target", target,
        "--project-dir", str(PROJECT_ROOT),
        "--profiles-dir", str(PROJECT_ROOT),
    ]
    if select:
        # la selezione puo' contenere piu' argomenti separati da spazi (unione)
        command += ["--select", *shlex.split(select)]
    if months:
        # mesi da caricare nei modelli incrementali (vedi macros/weather_months.sql)
        command += ["--vars", json.dumps({"months": list(months)})]
    if full_refresh:
        command.append("--full-refresh")
    logger.info(f"comando: {' '.join(command)}")

    try:
        # build = run + test (+ seed/snapshot) in ordine di dipendenza
        # popen con streaming riga per riga inoltra l'output al logger di prefect in tempo reale
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )

        for line in iter(process.stdout.readline, ""):
            stripped = line.strip()
            if stripped:
                logger.info(stripped)

        process.stdout.close()
        return_code = process.wait()

        if return_code != 0:
            raise RuntimeError(f"dbt build fallito (target={target}) con exit code {return_code}")

    finally:
        # pulizia per nome disattivata di default: le tabelle ducklake vive stanno in
        # cartelle '<tabella>__dbt_tmp/' (il rename di dbt cambia solo il catalogo).
        # riattivare con cleanup_tigris_tmp=true solo dopo aver risolto il layout dei percorsi.
        if os.getenv("CLEANUP_TIGRIS_TMP", "false").strip().lower() == "true":
            cleanup_tigris_tmp(target)


@task(name="Leggi registro caricamenti")
def read_load_log(months: int = REPORT_MONTHS):
    # legge dal registro audit.model_load_log le righe da riportare nella mail (vedi LOAD_LOG_QUERY):
    # [{"model_name": "weather_hourly_brz", "schema_name": "bronze", "load_date": "2026-11-08",
    #   "month_key": "2026-10", "rows_inserted": 545352, "logged_at": "2026-11-08 07:03:12"}, ...]
    # restituisce None se il registro non e' leggibile: la mail parte comunque, senza tabella.
    logger = get_run_logger()
    target = get_target()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["DBT_TARGET"] = target

    command = [
        "dbt", "show", "--quiet",
        "--output", "json",
        "--limit", "1000",
        "--inline", LOAD_LOG_QUERY.format(target=target, months=int(months)),
        "--target", target,
        "--project-dir", str(PROJECT_ROOT),
        "--profiles-dir", str(PROJECT_ROOT),
    ]
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    try:
        if result.returncode != 0:
            raise RuntimeError(f"dbt show ha restituito exit code {result.returncode}")
        output = result.stdout
        return json.loads(output[output.index("{"):])["show"]
    except Exception as exc:
        logger.warning(f"registro dei caricamenti non leggibile: {exc}\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        return None


@flow(
    name="ducklake-pipeline",
    log_prints=True,
    on_failure=[notify_on_failure]
)
def ducklake_flow(
    month: Optional[str] = None,
    start_month: Optional[str] = None,
    end_month: Optional[str] = None,
    max_months: Optional[int] = None,
    run_extract: bool = True,
    run_transform: bool = True,
    dbt_select: Optional[str] = None,
    full_refresh: bool = False,
):
    # month: mese da caricare (YYYY-MM); default il mese precedente (refresh mensile).
    # start_month / end_month: backfill di un intervallo di mesi; salta quelli gia' nel landing e si
    #   ferma al limite giornaliero dell'api. max_months limita i mesi estratti per esecuzione.
    # run_extract / run_transform: permettono di lanciare solo l'estrazione o solo dbt.
    # dbt_select: selezione dbt; vuota = tutti i modelli.
    # full_refresh: ricostruisce le tabelle rileggendo tutto il landing (dbt build --full-refresh).
    target = get_target()
    months = weather.resolve_months(month, start_month, end_month)

    if run_extract:
        months, _ = extract_weather(target, months, skip_existing=bool(start_month), max_months=max_months)

    if run_transform:
        if months or full_refresh:
            run_dbt(dbt_select, months, full_refresh)
        else:
            get_run_logger().info("nessun mese nuovo da caricare: dbt non viene eseguito")
        # mail di fine caricamento con la tabella del registro per il bronze (ultimi 10 mesi);
        # se qualcosa fallisce prima, parte invece la mail di errore di notify_on_failure
        notify_on_success(ducklake_flow.name, target, read_load_log(), months)


if __name__ == "__main__":
    ducklake_flow()
