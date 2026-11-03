"""Risorse temporanee per la CI: database Neon e prefisso Tigris isolati per ogni run.

Uso:
  python scripts/ci_resources.py create --pr 12 --run 123456_1
  python scripts/ci_resources.py drop   --pr 12 --run 123456_1   # solo le risorse di quel run
  python scripts/ci_resources.py drop   --pr 12                  # tutte quelle della PR

Variabili d'ambiente richieste:
  CI_NEON_BASE_URL   URL Neon del branch dev (stesso valore di NEON_URL_DEV)
  CI_TIGRIS_BASE     bucket di dev (stesso valore di TIGRIS_BUCKET_DEV)
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ENDPOINT_URL_S3   credenziali Tigris
Richiede il client "psql" installato.

Con "create" lo script aggiunge a $GITHUB_ENV le variabili NEON_URL_DEV e TIGRIS_BUCKET_DEV
puntate alle risorse temporanee: sono quelle lette da ducklake_plugin.py per il target dev.
"""
import argparse
import os
import re
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

import boto3


def die(msg: str):
    print(f"::error::{msg}", file=sys.stderr)
    sys.exit(1)


def neon_connection():
    raw = os.environ.get("CI_NEON_BASE_URL", "").strip()
    if not raw:
        die("CI_NEON_BASE_URL non impostata")
    u = urlsplit(raw)
    if not u.hostname or not u.username:
        die("CI_NEON_BASE_URL non e' un URL Postgres valido")

    host = u.hostname.replace("-pooler", "")  # il DDL va fatto sulla connessione diretta
    userinfo = u.netloc.rsplit("@", 1)[0]
    port = f":{u.port}" if u.port else ""
    sslmode = parse_qs(u.query).get("sslmode", ["require"])[0]

    env = os.environ.copy()
    env.update(
        PGHOST=host,
        PGPORT=str(u.port or 5432),
        PGUSER=unquote(u.username),
        PGPASSWORD=unquote(u.password or ""),
        PGDATABASE=(u.path.lstrip("/") or "neondb"),
        PGSSLMODE=sslmode,
    )

    def url_for(db: str) -> str:
        return urlunsplit((u.scheme, f"{userinfo}@{host}{port}", f"/{db}", u.query, ""))

    return env, url_for, unquote(u.password or "")


def psql(env, sql: str) -> str:
    try:
        res = subprocess.run(
            ["psql", "-v", "ON_ERROR_STOP=1", "-At", "-c", sql],
            env=env, check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        die("psql non trovato: installare postgresql-client")
    except subprocess.CalledProcessError as e:
        die(f"psql ha fallito su '{sql}': {e.stderr.strip()}")
    return res.stdout.strip()


def tigris_base():
    raw = os.environ.get("CI_TIGRIS_BASE", "").strip()
    if not raw:
        die("CI_TIGRIS_BASE non impostata")
    path = re.sub(r"^s3://", "", raw).strip("/")
    bucket, _, base = path.partition("/")
    base = f"{base.strip('/')}/" if base.strip("/") else ""
    return bucket, base


def s3_client():
    endpoint = os.environ.get("AWS_ENDPOINT_URL_S3", "").strip() or "t3.storage.dev"
    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def delete_prefix(bucket: str, prefix: str):
    # Sicurezza: si cancella solo sotto ci/pr-<n>/
    if "ci/pr-" not in prefix:
        die(f"prefisso non ammesso per la cancellazione: {prefix}")
    s3 = s3_client()
    deleted = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        for i in range(0, len(keys), 1000):
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys[i:i + 1000]})
            deleted += len(keys[i:i + 1000])
    print(f"[CI] Rimossi {deleted} oggetti da s3://{bucket}/{prefix}")


def write_github_env(values: dict):
    path = os.environ.get("GITHUB_ENV")
    lines = [f"{k}={v}" for k, v in values.items()]
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    else:
        print("GITHUB_ENV non impostato, variabili non esportate:", ", ".join(values))


def create(pr: str, run: str):
    env, url_for, password = neon_connection()
    bucket, base = tigris_base()
    db = f"ci_pr{pr}_{run}"
    ci_url = url_for(db)
    data_path = f"s3://{bucket}/{base}ci/pr-{pr}/run-{run}/"

    # Maschera i valori derivati, che non sono segreti registrati in GitHub
    if password:
        print(f"::add-mask::{password}")
    print(f"::add-mask::{ci_url}")

    psql(env, f'CREATE DATABASE "{db}"')
    print(f"[CI] Creato database Neon {db}; data path {data_path}")
    write_github_env({"NEON_URL_DEV": ci_url, "TIGRIS_BUCKET_DEV": data_path})


def drop(pr: str, run: str | None):
    env, _, _ = neon_connection()
    bucket, base = tigris_base()

    if run:
        dbs = [f"ci_pr{pr}_{run}"]
        prefix = f"{base}ci/pr-{pr}/run-{run}/"
    else:
        out = psql(env, f"select datname from pg_database where datname like 'ci\\_pr{pr}\\_%'")
        dbs = [d for d in out.splitlines() if d]
        prefix = f"{base}ci/pr-{pr}/"

    for db in dbs:
        psql(env, f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        print(f"[CI] Eliminato database Neon {db}")
    if not dbs:
        print("[CI] Nessun database Neon da eliminare")

    delete_prefix(bucket, prefix)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["create", "drop"])
    p.add_argument("--pr", required=True)
    p.add_argument("--run")
    a = p.parse_args()

    if not re.fullmatch(r"\d+", a.pr):
        die("--pr deve essere numerico")
    if a.run is not None and not re.fullmatch(r"\d+(_\d+)?", a.run):
        die("--run deve avere forma <run_id>_<tentativo>")

    if a.action == "create":
        if not a.run:
            die("--run e' obbligatorio per create")
        create(a.pr, a.run)
    else:
        drop(a.pr, a.run)


if __name__ == "__main__":
    main()
