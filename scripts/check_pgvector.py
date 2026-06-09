"""Verify Neon/Postgres has pgvector enabled — used from Phase 2 onward."""

from __future__ import annotations

import sys

from ledgerlens.config import get_settings


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL not set — copy .env.example to .env and add your Neon URL.")
        return 1

    try:
        import psycopg  # noqa: PLC0415
    except ImportError:
        print("psycopg not installed — run: pip install -e '.[storage]'")
        return 1

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()

            cur.execute("SELECT version()")
            pg_version = cur.fetchone()[0]

            cur.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            row = cur.fetchone()
            if row is None:
                print("pgvector extension is not available on this server.")
                return 1
            vector_version = row[0]

    print(f"Postgres: {pg_version}")
    print(f"pgvector: {vector_version}")
    print("pgvector check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
