import os

import psycopg


def main() -> None:
    with psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT api.refresh_views()")

    print("source-etl api views refreshed", flush=True)


if __name__ == "__main__":
    main()
