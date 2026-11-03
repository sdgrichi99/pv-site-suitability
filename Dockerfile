FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia i file del progetto
COPY . .

# Copia il plugin dentro i site-packages di sistema del container (esattamente come fai in locale)
RUN cp ducklake_plugin.py /usr/local/lib/python3.11/site-packages/

RUN dbt deps || true

CMD ["python", "orchestrate/main_flow.py"]