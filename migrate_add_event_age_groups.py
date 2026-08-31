"""
Idempotent migration: add age_groups TEXT column to events table.

Run once on the production database. Safe to re-run — ADD COLUMN IF NOT EXISTS
is a no-op when the column already exists.

Usage:
    python migrate_add_event_age_groups.py
"""
import os
import sys

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
    sys.exit(1)

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    conn.execute(text(
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS age_groups TEXT"
    ))
    conn.commit()

print("Migration complete: events.age_groups column is present.")
