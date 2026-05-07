FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ETL_HOME=/app \
    ETL_STATE_DIR=/var/lib/github-etl/state

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "meltanolabs-tap-github" \
    "meltanolabs-target-postgres"

COPY . /app

RUN chmod +x /app/entrypoint.sh /app/run-etl.sh

ENTRYPOINT ["/app/entrypoint.sh"]
