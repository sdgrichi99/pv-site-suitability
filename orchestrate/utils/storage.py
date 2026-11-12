"""Scrittura dei file grezzi (landing) su Tigris.

Il bucket di destinazione e le credenziali dipendono dal target, con le stesse variabili
usate da profiles.yml e da ducklake_plugin.py:
  dev: TIGRIS_BUCKET_DEV, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ENDPOINT_URL_S3
  prd: TIGRIS_BUCKET_PRD, AWS_ACCESS_KEY_ID_PRD, AWS_SECRET_ACCESS_KEY_PRD, AWS_ENDPOINT_URL_S3_PRD

I file vanno sotto <bucket>/<eventuale prefisso>/landing/<sorgente>/...
Le tabelle di dbt leggono lo stesso percorso con la macro landing_path.
"""
import gzip
import json
import os
import re

import boto3
from botocore.exceptions import ClientError

VALID_TARGETS = ("dev", "prd")


def _check_target(target: str) -> str:
    target = target.strip().lower()
    if target not in VALID_TARGETS:
        raise ValueError(f"target deve essere uno tra {VALID_TARGETS}, ricevuto '{target}'")
    return target


def bucket_and_prefix(target: str):
    """Restituisce (bucket, prefisso) da TIGRIS_BUCKET_<DEV|PRD>; il prefisso termina con '/' o e' vuoto."""
    target = _check_target(target)
    var = f"TIGRIS_BUCKET_{target.upper()}"
    raw = os.environ.get(var, "").strip()
    if not raw:
        raise ValueError(f"variabile d'ambiente {var} non impostata")
    path = re.sub(r"^s3://", "", raw).strip("/")
    bucket, _, prefix = path.partition("/")
    prefix = f"{prefix.strip('/')}/" if prefix.strip("/") else ""
    return bucket, prefix


def s3_client(target: str):
    target = _check_target(target)
    if target == "prd":
        endpoint = os.environ.get("AWS_ENDPOINT_URL_S3_PRD", "")
        key_id = os.environ.get("AWS_ACCESS_KEY_ID_PRD")
        secret = os.environ.get("AWS_SECRET_ACCESS_KEY_PRD")
    else:
        endpoint = os.environ.get("AWS_ENDPOINT_URL_S3", "")
        key_id = os.environ.get("AWS_ACCESS_KEY_ID")
        secret = os.environ.get("AWS_SECRET_ACCESS_KEY")

    endpoint = endpoint.strip() or "t3.storage.dev"
    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name="auto",
    )


def _full_key(target: str, relative_key: str):
    bucket, prefix = bucket_and_prefix(target)
    return bucket, f"{prefix}{relative_key.lstrip('/')}"


def put_json_gz(target: str, relative_key: str, payload) -> str:
    """Scrive payload come JSON compatto compresso con gzip in <prefisso>/<relative_key>.
    Sovrascrive se la chiave esiste. Restituisce il percorso s3:// completo."""
    bucket, key = _full_key(target, relative_key)
    body = gzip.compress(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    s3_client(target).put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/gzip")
    return f"s3://{bucket}/{key}"


def put_text(target: str, relative_key: str, text: str) -> str:
    """Scrive un piccolo file di testo (ad esempio il marcatore _SUCCESS)."""
    bucket, key = _full_key(target, relative_key)
    s3_client(target).put_object(Bucket=bucket, Key=key, Body=text.encode("utf-8"), ContentType="text/plain")
    return f"s3://{bucket}/{key}"


def object_exists(target: str, relative_key: str) -> bool:
    bucket, key = _full_key(target, relative_key)
    try:
        s3_client(target).head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def put_json(target: str, relative_key: str, payload: dict) -> str:
    """Scrive payload come JSON compatto in <prefisso>/<relative_key>. Sovrascrive se la chiave esiste.

    Restituisce il percorso s3:// completo.
    """
    bucket, prefix = bucket_and_prefix(target)
    key = f"{prefix}{relative_key.lstrip('/')}"
    s3_client(target).put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{bucket}/{key}"
