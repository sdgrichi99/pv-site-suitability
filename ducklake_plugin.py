import os
 
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
 
 
class Plugin(BasePlugin):
    def initialize(self, config):
        # Nessun default: un env_suffix mancante o con nome errato deve fallire,
        # non ripiegare silenziosamente su DEV.
        raw_suffix = (config or {}).get("env_suffix")
        if raw_suffix is None:
            raise ValueError(
                "ducklake_plugin: 'env_suffix' is required in the plugin config "
                f"(one of {VALID_SUFFIXES})"
            )
        suffix = str(raw_suffix).upper()
        if suffix not in VALID_SUFFIXES:
            raise ValueError(f"ducklake_plugin: env_suffix must be one of {VALID_SUFFIXES}, got '{suffix}'")
        self.suffix = suffix
 
    def configure_connection(self, conn):
        neon_url = _require(f"NEON_URL_{self.suffix}").replace("&channel_binding=require", "")
        data_path = _require(f"TIGRIS_BUCKET_{self.suffix}")
 
        neon_url = _sql_literal(neon_url)
        data_path = _sql_literal(data_path)
 
        # 1. Plain Neon Postgres
        conn.execute(f"ATTACH IF NOT EXISTS '{neon_url}' AS pg_db (TYPE POSTGRES);")
 
        # 2. DuckLake: metadata in the same Neon database, Parquet files on Tigris
        conn.execute(
            f"""
            ATTACH IF NOT EXISTS 'postgres:{neon_url}' AS lakehouse (
                TYPE DUCKLAKE,
                DATA_PATH '{data_path}'
            );
            """
        )
