# Source ETLs

Host-side ETL stack for GitHub and NVIDIA forum data used by the NVIDIA Hermes
setup path.

This stack is intentionally outside OpenShell. Hermes is expected to query the
read-only PostgREST bridge rather than reaching GitHub or the NVIDIA forums
directly.

## Defaults

- GitHub repo: `NVIDIA/NemoClaw`
- NVIDIA forums tag: `nemoclaw`
- initial backfill: 72 hours
- recurring refresh: hourly

## Services

- `postgres`: shared sink and ETL metadata store
- `github-etl`: GitHub issues/PRs/discussions ingestion
- `forums-etl`: NVIDIA forums Discourse JSON ingestion
- `postgrest`: read-only HTTP API bridge for Hermes queries

## Environment

Export the repo root `.env` before running compose. Relevant variables:

- `SOURCE_ETL_GITHUB_REPO`
- `SOURCE_ETL_FORUM_TAG`
- `SOURCE_ETL_POSTGRES_HOST`
- `SOURCE_ETL_POSTGRES_PORT`
- `SOURCE_ETL_POSTGRES_DB`
- `SOURCE_ETL_POSTGRES_SUPERUSER`
- `SOURCE_ETL_POSTGRES_SUPERUSER_PASSWORD`
- `SOURCE_ETL_POSTGRES_APP_USER`
- `SOURCE_ETL_POSTGRES_APP_PASSWORD`
- `SOURCE_ETL_POSTGRES_READER_USER`
- `SOURCE_ETL_POSTGRES_READER_PASSWORD`
- `SOURCE_ETL_API_PORT`
- `SOURCE_ETL_OPENSHELL_NETWORK`
- `GITHUB_TOKEN`

## Run

Run this after the OpenShell gateway has created the external
`SOURCE_ETL_OPENSHELL_NETWORK` network.

```bash
set -a && source .env && set +a
cd source-etls
docker compose up -d --build
```

The ETL containers run once immediately on startup and then sleep until the next
hourly refresh window.

Role split:

- ETLs connect with `SOURCE_ETL_POSTGRES_APP_USER`
- PostgREST connects with `SOURCE_ETL_POSTGRES_READER_USER`; Hermes only reaches
  the read-only REST bridge
