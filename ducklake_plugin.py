import os
import re
import sys

from dbt.adapters.duckdb.plugins import BasePlugin

VALID_SUFFIXES = ("DEV", "PRD")


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"ducklake_plugin: environment variable {name} is not set")
    return value


def _sql_literal(value: str) -> str:
    """Escape single quotes so passwords/paths cannot break the SQL string."""
    return value.replace("'", "''")


def _redact(text: str, secrets=()) -> str:
    """Oscura nei messaggi gli URL di connessione e i valori segreti noti."""
    for value in secrets:
        if value:
            text = text.replace(value, "***")
    # Qualunque URL postgres://utente:password@host  ->  postgres://utente:***@host
    return re.sub(r"(postgres(?:ql)?://[^:/\s@]+:)[^@\s\"']+@", r"\1***@", text)


def _warn(message: str) -> None:
    print(f"[ducklake_plugin] WARNING: {message}", file=sys.stderr)


class Plugin(BasePlugin):
    def initialize(self, config):
        config = config or {}
        # Nessun default: un env_suffix mancante o con nome errato deve fallire,
        # non ripiegare silenziosamente su DEV.
        raw_suffix = config.get("env_suffix")
        if raw_suffix is None:
            raise ValueError(
                "ducklake_plugin: 'env_suffix' is required in the plugin config "
                f"(one of {VALID_SUFFIXES})"
            )
        suffix = str(raw_suffix).upper()
        if suffix not in VALID_SUFFIXES:
            raise ValueError(f"ducklake_plugin: env_suffix must be one of {VALID_SUFFIXES}, got '{suffix}'")
        self.suffix = suffix
        # Solo per il target dev: aggancia anche il catalogo di produzione in sola lettura
        # (alias lakehouse_prd), cosi' dbt puo' fare defer verso i dati di produzione.
        self.attach_prd_readonly = bool(config.get("attach_prd_readonly", False))

    def configure_connection(self, conn):
        neon_url = _require(f"NEON_URL_{self.suffix}").replace("&channel_binding=require", "")
        data_path = _require(f"TIGRIS_BUCKET_{self.suffix}")

        neon_url = _sql_literal(neon_url)
        data_path = _sql_literal(data_path)

        # Alias del catalogo di questo target: lakehouse_dev oppure lakehouse_prd.
        # Deve coincidere con +database in dbt_project.yml.
        alias = f"lakehouse_{self.suffix.lower()}"

        # 1. Plain Neon Postgres
        conn.execute(f"ATTACH IF NOT EXISTS '{neon_url}' AS pg_db (TYPE POSTGRES);")

        # 2. DuckLake: metadata in the same Neon database, Parquet files on Tigris
        conn.execute(
            f"""
            ATTACH IF NOT EXISTS 'postgres:{neon_url}' AS {alias} (
                TYPE DUCKLAKE,
                DATA_PATH '{data_path}'
            );
            """
        )

        # 3. Solo dev e solo se richiesto nel profilo: catalogo di produzione in sola lettura
        if self.suffix == "DEV" and self.attach_prd_readonly:
            self._attach_prd_readonly(conn)

    def _attach_prd_readonly(self, conn):
        prd_url = os.getenv("NEON_URL_PRD", "").strip()
        prd_path = os.getenv("TIGRIS_BUCKET_PRD", "").strip()
        key_id = os.getenv("AWS_ACCESS_KEY_ID_PRD", "").strip()
        secret = os.getenv("AWS_SECRET_ACCESS_KEY_PRD", "").strip()
        endpoint = os.getenv("AWS_ENDPOINT_URL_S3_PRD", "").strip()
        region = os.getenv("AWS_REGION_PRD", "auto").strip() or "auto"

        required = (prd_url, prd_path, key_id, secret, endpoint)
        if not any(required):
            # Nessuna variabile di produzione (CI, Prefect dev): niente da agganciare.
            return
        if not all(required):
            _warn(
                "variabili di produzione incomplete (servono NEON_URL_PRD, TIGRIS_BUCKET_PRD, "
                "AWS_ACCESS_KEY_ID_PRD, AWS_SECRET_ACCESS_KEY_PRD, AWS_ENDPOINT_URL_S3_PRD): "
                "catalogo lakehouse_prd NON agganciato"
            )
            return

        prd_url = prd_url.replace("&channel_binding=require", "")
        endpoint = endpoint.replace("https://", "").replace("http://", "").rstrip("/")
        scope = prd_path if prd_path.startswith("s3://") else f"s3://{prd_path}"
        if not scope.endswith("/"):
            scope += "/"

        try:
            # Segreto S3 limitato al bucket di produzione: le credenziali di dev
            # (segreto del profilo, senza scope) continuano a valere per il bucket di dev.
            conn.execute(
                f"""
                CREATE OR REPLACE SECRET tigris_prd (
                    TYPE S3,
                    KEY_ID '{_sql_literal(key_id)}',
                    SECRET '{_sql_literal(secret)}',
                    ENDPOINT '{_sql_literal(endpoint)}',
                    URL_STYLE 'path',
                    USE_SSL true,
                    REGION '{_sql_literal(region)}',
                    SCOPE '{_sql_literal(scope)}'
                );
                """
            )
            conn.execute(
                f"""
                ATTACH IF NOT EXISTS 'postgres:{_sql_literal(prd_url)}' AS lakehouse_prd (
                    TYPE DUCKLAKE,
                    DATA_PATH '{_sql_literal(prd_path)}',
                    READ_ONLY
                );
                """
            )
        except Exception as exc:  # il catalogo prd puo' non essere ancora inizializzato
            # Il messaggio di DuckDB contiene l'URL di connessione: va oscurato prima di stamparlo.
            _warn(
                "impossibile agganciare lakehouse_prd in sola lettura: "
                + _redact(str(exc), (prd_url, key_id, secret))
            )
