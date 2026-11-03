import os
from pathlib import Path
import duckdb
from dotenv import load_dotenv

load_dotenv()

manifest_file = Path("target/manifest.json")
if not manifest_file.exists():
    raise FileNotFoundError(f"File {manifest_file} not found")

# Pulizia rigorosa di endpoint, bucket e slash finali
endpoint = os.getenv("AWS_ENDPOINT_URL_S3_PRD", "https://t3.storage.dev").replace("https://", "").replace("http://", "").strip().rstrip("/")
bucket = os.getenv("TIGRIS_BUCKET_PRD", "").replace("s3://", "").strip().strip("/")
key = "metadata/manifest.json"
s3_target_url = f"s3://{bucket}/{key}"

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

print(f"Caricamento manifest su {s3_target_url}...")

manifest_content = manifest_file.read_text(encoding="utf-8")

con.execute(
    f"COPY (SELECT ? AS json_data) TO '{s3_target_url}' (FORMAT CSV, HEADER 0, QUOTE '');",
    [manifest_content]
)

print("manifest is loaded on tigris")
