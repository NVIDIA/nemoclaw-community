from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable

import dlt
import httpx
import psycopg

FORUM_BASE_URL = os.environ.get("SOURCE_ETL_FORUM_BASE_URL", "https://forums.developer.nvidia.com")
FORUM_TAG = os.environ.get("SOURCE_ETL_FORUM_TAG", "nemoclaw")
INITIAL_BACKFILL_HOURS = int(os.environ.get("ETL_INITIAL_BACKFILL_HOURS", "72"))
OVERLAP_HOURS = int(os.environ.get("ETL_OVERLAP_HOURS", "72"))

POSTGRES_HOST = os.environ["POSTGRES_HOST"]
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ["POSTGRES_DB"]
POSTGRES_USER = os.environ["POSTGRES_USER"]
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def pg_dsn() -> str:
    return (
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )


def ensure_metadata_table() -> None:
    with psycopg.connect(pg_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS etl_metadata (
                  source_name TEXT PRIMARY KEY,
                  last_success_at TIMESTAMPTZ
                )
                """
            )
        conn.commit()


def get_lower_bound() -> datetime:
    ensure_metadata_table()
    floor = utc_now() - timedelta(hours=INITIAL_BACKFILL_HOURS)
    with psycopg.connect(pg_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_success_at FROM etl_metadata WHERE source_name = %s",
                ("nvidia_forums",),
            )
            row = cur.fetchone()
    if not row or not row[0]:
        return floor
    return max(floor, row[0] - timedelta(hours=OVERLAP_HOURS))


def mark_success() -> None:
    with psycopg.connect(pg_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO etl_metadata (source_name, last_success_at)
                VALUES (%s, %s)
                ON CONFLICT (source_name)
                DO UPDATE SET last_success_at = EXCLUDED.last_success_at
                """,
                ("nvidia_forums", utc_now()),
            )
        conn.commit()


def request_json(client: httpx.Client, url: str) -> dict:
    resp = client.get(
        url,
        headers={"Accept": "application/json", "User-Agent": "NemoClaw source-etls forums-etl"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def topic_changed_after(topic: dict, lower_bound: datetime) -> bool:
    candidates = [
        parse_ts(topic.get("last_posted_at")),
        parse_ts(topic.get("bumped_at")),
        parse_ts(topic.get("created_at")),
    ]
    return any(ts and ts >= lower_bound for ts in candidates)


def fetch_tag_topics(client: httpx.Client, lower_bound: datetime) -> list[dict]:
    page = 0
    topics: list[dict] = []
    while True:
        suffix = f"/tag/{FORUM_TAG}.json" if page == 0 else f"/tag/{FORUM_TAG}.json?page={page}"
        payload = request_json(client, f"{FORUM_BASE_URL}{suffix}")
        page_topics = payload.get("topic_list", {}).get("topics", [])
        if not page_topics:
            break
        recent = [topic for topic in page_topics if topic_changed_after(topic, lower_bound)]
        topics.extend(recent)
        if len(recent) != len(page_topics):
            break
        page += 1
    deduped = {topic["id"]: topic for topic in topics}
    return list(deduped.values())


def fetch_topic_details(client: httpx.Client, topics: Iterable[dict]) -> list[dict]:
    details: list[dict] = []
    for topic in topics:
        topic_id = topic["id"]
        slug = topic["slug"]
        details.append(request_json(client, f"{FORUM_BASE_URL}/t/{slug}/{topic_id}.json"))
    return details


def topic_rows(details: Iterable[dict]) -> list[dict]:
    rows = []
    for detail in details:
        rows.append(
            {
                "topic_id": detail["id"],
                "slug": detail.get("slug"),
                "title": detail.get("title"),
                "category_id": detail.get("category_id"),
                "created_at": detail.get("created_at"),
                "last_posted_at": detail.get("last_posted_at"),
                "tags": detail.get("tags", []),
                "views": detail.get("views"),
                "like_count": detail.get("like_count"),
                "reply_count": detail.get("reply_count"),
                "raw_payload": json.dumps(detail),
            }
        )
    return rows


def post_rows(details: Iterable[dict]) -> list[dict]:
    rows = []
    for detail in details:
        topic_id = detail["id"]
        for post in detail.get("post_stream", {}).get("posts", []):
            rows.append(
                {
                    "post_id": post["id"],
                    "topic_id": topic_id,
                    "post_number": post.get("post_number"),
                    "username": post.get("username"),
                    "created_at": post.get("created_at"),
                    "updated_at": post.get("updated_at"),
                    "reply_count": post.get("reply_count"),
                    "cooked": post.get("cooked"),
                    "raw_payload": json.dumps(post),
                }
            )
    return rows


@dlt.resource(name="forum_topics", write_disposition="merge", primary_key="topic_id")
def forum_topics_resource(rows: list[dict]) -> Iterable[dict]:
    yield from rows


@dlt.resource(name="forum_posts", write_disposition="merge", primary_key="post_id")
def forum_posts_resource(rows: list[dict]) -> Iterable[dict]:
    yield from rows


def main() -> None:
    lower_bound = get_lower_bound()
    with httpx.Client(follow_redirects=True) as client:
        topics = fetch_tag_topics(client, lower_bound)
        details = fetch_topic_details(client, topics)

    topic_data = topic_rows(details)
    post_data = post_rows(details)

    pipeline = dlt.pipeline(
        pipeline_name="nvidia_forums_etl",
        destination="postgres",
        dataset_name="forums_etl",
    )
    pipeline.run(
        [
            forum_topics_resource(topic_data),
            forum_posts_resource(post_data),
        ],
        destination=dlt.destinations.postgres(
            credentials=pg_dsn(),
        ),
    )
    mark_success()


if __name__ == "__main__":
    main()
