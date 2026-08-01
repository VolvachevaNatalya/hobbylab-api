"""Migration: add event_series table and recurrence columns to events.

Run manually after deploying the updated code. Safe to run multiple times.
Does NOT run the series generation — only adds schema.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

if not os.environ.get("DATABASE_URL"):
    load_dotenv(os.path.join(os.path.dirname(__file__), "app", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL)


def table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": table},
    ).fetchone()
    return row is not None


def column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


with engine.begin() as conn:
    # ── event_series table ────────────────────────────────────────────────────
    if not table_exists(conn, "event_series"):
        conn.execute(text("""
            CREATE TABLE event_series (
                id          SERIAL PRIMARY KEY,
                frequency   VARCHAR(20)  NOT NULL,
                interval    INTEGER      NOT NULL DEFAULT 1,
                end_type    VARCHAR(10)  NOT NULL,
                total_count INTEGER,
                end_date    DATE,
                generated_until TIMESTAMP,
                status      VARCHAR(20)  NOT NULL DEFAULT 'active',
                created_at  TIMESTAMP    DEFAULT now()
            )
        """))
        print("Created table: event_series")
    else:
        print("Table already exists: event_series")

    # ── events columns ────────────────────────────────────────────────────────
    if not column_exists(conn, "events", "series_id"):
        conn.execute(text(
            "ALTER TABLE events "
            "ADD COLUMN series_id INTEGER REFERENCES event_series(id) ON DELETE SET NULL"
        ))
        print("Added column: events.series_id")

    if not column_exists(conn, "events", "occurrence_index"):
        conn.execute(text("ALTER TABLE events ADD COLUMN occurrence_index INTEGER"))
        print("Added column: events.occurrence_index")

    if not column_exists(conn, "events", "original_start_datetime"):
        conn.execute(text("ALTER TABLE events ADD COLUMN original_start_datetime TIMESTAMP"))
        print("Added column: events.original_start_datetime")

    # ── indexes ───────────────────────────────────────────────────────────────
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_events_series_id ON events (series_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_events_occurrence ON events (series_id, occurrence_index)"
    ))
    print("Indexes ensured.")

print("Migration complete.")
