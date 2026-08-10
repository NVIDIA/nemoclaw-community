#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import os

import psycopg
from psycopg import sql


EMPTY_FORUM_TOPICS_VIEW = """
CREATE VIEW api.forum_topics AS
SELECT
    NULL::bigint AS topic_id,
    NULL::text AS slug,
    NULL::text AS title,
    NULL::timestamp with time zone AS created_at,
    NULL::timestamp with time zone AS last_posted_at,
    NULL::bigint AS views,
    NULL::bigint AS like_count,
    NULL::bigint AS reply_count,
    NULL::text AS raw_payload,
    NULL::text AS raw_payload_text
WHERE false
"""


def main() -> None:
    with psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('forums_etl.forum_topics')")
            forum_topics_exists = cur.fetchone()[0] is not None

            # dlt does not create a destination table when a source returns no
            # rows. Keep PostgREST's documented empty-array contract instead
            # of returning 404 until the first matching forum topic arrives.
            if not forum_topics_exists:
                cur.execute("DROP VIEW IF EXISTS api.forum_topics")
                cur.execute(EMPTY_FORUM_TOPICS_VIEW)
                cur.execute(
                    sql.SQL("GRANT SELECT ON api.forum_topics TO {}").format(
                        sql.Identifier(
                            os.environ.get(
                                "SOURCE_ETL_POSTGRES_READER_USER",
                                "source_etl_reader",
                            )
                        )
                    )
                )
                cur.execute("NOTIFY pgrst, 'reload schema'")
            else:
                # Drop the typed empty fallback in the same transaction before
                # replacing it with the view over dlt's inferred table schema.
                cur.execute("DROP VIEW IF EXISTS api.forum_topics")
                cur.execute("SELECT api.refresh_views()")

    print("source-etl api views refreshed", flush=True)


if __name__ == "__main__":
    main()
