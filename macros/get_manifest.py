import os
from pathlib import Path
import duckdb
from dotenv import load_dotenv

load_dotenv()

# Cartella di destinazione per il manifest scaricato
target_dir = Path("prod_artifacts")
target_dir.mkdir(parents=True, exist_ok=True)
dest_file = target_dir / "manifest.json"

endpoint = os.getenv("AWS_ENDPOINT_URL_S3_PRD", "https://t3.storage.dev").replace("https://", "").replace("http://", "").strip().rstrip("/")
bucket = os.getenv("TIGRIS_BUCKET_PRD", "").replace("s3://", "").strip().strip("/")
key = "metadata/manifest.json"
s3_source_url = f"s3://{bucket}/{key}"

access_key = os.getenv("AWS_ACCESS_KEY_ID_PRD", "").strip()
secret_key = os.getenv("AWS_SECRET_ACCESS_KEY_PRD", "").strip()
region = os.getenv("AWS_REGION_PRD", "auto").strip()

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")

con.execute(f"""
    CREATE OR REPLACE SECRET tigris_s3 (
        TYPE S3,
        KEY_ID '{access_key}',
        SECRET '{secret_key}',
        REGION '{region}',
        ENDPOINT '{endpoint}',
        URL_STYLE 'path',
        USE_SSL true
    );
""")

print(f"Scaricamento manifest da {s3_source_url}...")

result = con.execute(f"SELECT content FROM read_text('{s3_source_url}')").fetchone()

if result and result[0]:
    dest_file.write_text(result[0], encoding="utf-8")
    print(f"Manifest scaricato con successo in: {dest_file}")
else:
    raise FileNotFoundError(f"Impossibile recuperare il file da {s3_source_url}")
