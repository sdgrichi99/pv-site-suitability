import os
import sys
import subprocess
from pathlib import Path
import boto3
from prefect import flow, task, get_run_logger
from orchestrate.utils.notifications import notify_on_failure

# risolve la root del progetto (la cartella genitore rispetto a /orchestrate)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# la root va aggiunta a sys.path prima di importare 'orchestrate' e 'ducklake_plugin':
# con prefect managed il progetto viene clonato in una cartella temporanea.
sys.path.append(str(PROJECT_ROOT))

VALID_TARGETS = ("dev", "prd")


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


@task(name="Esegui Pipeline dbt")
def run_dbt():
    logger = get_run_logger()
    target = get_target()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["DBT_TARGET"] = target

    try:
        # build = run + test (+ seed/snapshot) in ordine di dipendenza
        # popen con streaming riga per riga inoltra l'output al logger di prefect in tempo reale
        process = subprocess.Popen(
            [
                "dbt", "build",
                "--target", target,
                "--project-dir", str(PROJECT_ROOT),
                "--profiles-dir", str(PROJECT_ROOT),
            ],
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


@flow(
    name="ducklake-pipeline",
    on_failure=[notify_on_failure]
)
def ducklake_flow():
    run_dbt()


if __name__ == "__main__":
    ducklake_flow()