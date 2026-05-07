# GitHub ETL

Host-side GitHub ETL container for hourly Singer syncs from `MeltanoLabs/tap-github`
into Postgres via `MeltanoLabs/target-postgres`.

## Behavior

- Runs once immediately, then every hour by default.
- Uses a 72-hour backfill window on first run when no prior Singer state exists.
- Reuses saved state on later runs for incremental syncs.
- Targets one repo by default: `NVIDIA/NemoClaw`.

## Required Env

- `POSTGRES_HOST`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`

## Optional Env

- `GITHUB_REPOSITORY` default `NVIDIA/NemoClaw`
- `GITHUB_TOKEN` optional but strongly recommended for rate limits
- `POSTGRES_PORT` default `5432`
- `POSTGRES_SCHEMA` default `github_raw`
- `POSTGRES_SQLALCHEMY_URL` overrides the discrete Postgres fields
- `BACKFILL_HOURS` default `72`
- `SYNC_INTERVAL_SECONDS` default `3600`
- `ETL_STATE_DIR` default `/var/lib/github-etl/state`
- `ETL_RUNTIME_DIR` default `/app/.runtime`
- `ETL_LOG_LEVEL` default `INFO`

## Compose Assumptions

- Build context points at `source-etls/github-etl`.
- Persist `ETL_STATE_DIR` on a named volume or bind mount.
- Put the service on the same network as the Postgres service.
- Supply env via compose or an env file; no repo-wide compose changes are made here.

## Local Run

```bash
docker build -t github-etl ./source-etls/github-etl
docker run --rm \
  -e POSTGRES_HOST=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=postgres \
  -e GITHUB_TOKEN=ghp_xxx \
  github-etl
```
