#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${SOURCE_ETL_POSTGRES_APP_USER}') THEN
      CREATE ROLE ${SOURCE_ETL_POSTGRES_APP_USER} LOGIN PASSWORD '${SOURCE_ETL_POSTGRES_APP_PASSWORD}';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${SOURCE_ETL_POSTGRES_READER_USER}') THEN
      CREATE ROLE ${SOURCE_ETL_POSTGRES_READER_USER} LOGIN PASSWORD '${SOURCE_ETL_POSTGRES_READER_PASSWORD}';
    END IF;
  END
  \$\$;

  GRANT CONNECT, CREATE, TEMPORARY ON DATABASE ${POSTGRES_DB} TO ${SOURCE_ETL_POSTGRES_APP_USER};
  GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${SOURCE_ETL_POSTGRES_READER_USER};
  GRANT USAGE, CREATE ON SCHEMA public TO ${SOURCE_ETL_POSTGRES_APP_USER};
  GRANT USAGE ON SCHEMA public TO ${SOURCE_ETL_POSTGRES_READER_USER};
  CREATE SCHEMA IF NOT EXISTS github_raw AUTHORIZATION ${SOURCE_ETL_POSTGRES_APP_USER};
  CREATE SCHEMA IF NOT EXISTS forums_etl AUTHORIZATION ${SOURCE_ETL_POSTGRES_APP_USER};
  CREATE SCHEMA IF NOT EXISTS api AUTHORIZATION ${SOURCE_ETL_POSTGRES_APP_USER};
  GRANT USAGE ON SCHEMA github_raw TO ${SOURCE_ETL_POSTGRES_READER_USER};
  GRANT USAGE ON SCHEMA forums_etl TO ${SOURCE_ETL_POSTGRES_READER_USER};
  GRANT USAGE ON SCHEMA api TO ${SOURCE_ETL_POSTGRES_READER_USER};
  GRANT SELECT ON ALL TABLES IN SCHEMA github_raw TO ${SOURCE_ETL_POSTGRES_READER_USER};
  GRANT SELECT ON ALL SEQUENCES IN SCHEMA github_raw TO ${SOURCE_ETL_POSTGRES_READER_USER};
  GRANT SELECT ON ALL TABLES IN SCHEMA forums_etl TO ${SOURCE_ETL_POSTGRES_READER_USER};
  GRANT SELECT ON ALL SEQUENCES IN SCHEMA forums_etl TO ${SOURCE_ETL_POSTGRES_READER_USER};
  GRANT SELECT ON ALL TABLES IN SCHEMA api TO ${SOURCE_ETL_POSTGRES_READER_USER};
  GRANT SELECT ON ALL SEQUENCES IN SCHEMA api TO ${SOURCE_ETL_POSTGRES_READER_USER};
  ALTER DEFAULT PRIVILEGES FOR ROLE ${SOURCE_ETL_POSTGRES_APP_USER} IN SCHEMA api
    GRANT SELECT ON TABLES TO ${SOURCE_ETL_POSTGRES_READER_USER};
  ALTER DEFAULT PRIVILEGES FOR ROLE ${SOURCE_ETL_POSTGRES_APP_USER} IN SCHEMA api
    GRANT SELECT ON SEQUENCES TO ${SOURCE_ETL_POSTGRES_READER_USER};
  ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO ${SOURCE_ETL_POSTGRES_READER_USER};
  ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO ${SOURCE_ETL_POSTGRES_READER_USER};
  ALTER DEFAULT PRIVILEGES FOR ROLE ${SOURCE_ETL_POSTGRES_APP_USER} IN SCHEMA github_raw
    GRANT SELECT ON TABLES TO ${SOURCE_ETL_POSTGRES_READER_USER};
  ALTER DEFAULT PRIVILEGES FOR ROLE ${SOURCE_ETL_POSTGRES_APP_USER} IN SCHEMA github_raw
    GRANT SELECT ON SEQUENCES TO ${SOURCE_ETL_POSTGRES_READER_USER};
  ALTER DEFAULT PRIVILEGES FOR ROLE ${SOURCE_ETL_POSTGRES_APP_USER} IN SCHEMA forums_etl
    GRANT SELECT ON TABLES TO ${SOURCE_ETL_POSTGRES_READER_USER};
  ALTER DEFAULT PRIVILEGES FOR ROLE ${SOURCE_ETL_POSTGRES_APP_USER} IN SCHEMA forums_etl
    GRANT SELECT ON SEQUENCES TO ${SOURCE_ETL_POSTGRES_READER_USER};

  SET ROLE ${SOURCE_ETL_POSTGRES_APP_USER};

  CREATE OR REPLACE FUNCTION api.refresh_views()
    RETURNS void
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, public
  AS \$refresh_views\$
  BEGIN
    IF to_regclass('github_raw.issues') IS NOT NULL THEN
      EXECUTE 'CREATE OR REPLACE VIEW api.github_issues AS
        SELECT
          org,
          repo,
          number,
          state,
          updated_at,
          created_at,
          closed_at,
          title,
          body,
          html_url
        FROM github_raw.issues';
      EXECUTE format('GRANT SELECT ON api.github_issues TO %I', '${SOURCE_ETL_POSTGRES_READER_USER}');
    END IF;

    IF to_regclass('github_raw.pull_requests') IS NOT NULL THEN
      EXECUTE 'CREATE OR REPLACE VIEW api.github_prs AS
        SELECT
          org,
          repo,
          number,
          state,
          updated_at,
          created_at,
          closed_at,
          merged_at,
          draft,
          title,
          body,
          html_url
        FROM github_raw.pull_requests';
      EXECUTE format('GRANT SELECT ON api.github_prs TO %I', '${SOURCE_ETL_POSTGRES_READER_USER}');
    END IF;

    IF to_regclass('github_raw.discussions') IS NOT NULL THEN
      EXECUTE 'CREATE OR REPLACE VIEW api.github_discussions AS
        SELECT
          org,
          repo,
          number,
          updated_at,
          created_at,
          closed_at,
          closed,
          is_answered,
          title,
          body,
          url
        FROM github_raw.discussions';
      EXECUTE format('GRANT SELECT ON api.github_discussions TO %I', '${SOURCE_ETL_POSTGRES_READER_USER}');
    END IF;

    IF to_regclass('forums_etl.forum_topics') IS NOT NULL THEN
      EXECUTE 'CREATE OR REPLACE VIEW api.forum_topics AS
        SELECT
          topic_id,
          slug,
          title,
          created_at,
          last_posted_at,
          views,
          like_count,
          reply_count,
          raw_payload,
          raw_payload::text AS raw_payload_text
        FROM forums_etl.forum_topics';
      EXECUTE format('GRANT SELECT ON api.forum_topics TO %I', '${SOURCE_ETL_POSTGRES_READER_USER}');
    END IF;

    PERFORM pg_notify('pgrst', 'reload schema');
  END
  \$refresh_views\$;

  SELECT api.refresh_views();

  RESET ROLE;

  GRANT EXECUTE ON FUNCTION api.refresh_views() TO ${SOURCE_ETL_POSTGRES_APP_USER};
SQL
