"""
Migration: create event_categories table and backfill from events.category_id.
Safe to run more than once — CREATE TABLE IF NOT EXISTS and ON CONFLICT DO NOTHING.
Run: python migrate_add_event_categories.py
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL)
with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS event_categories (
            event_id    INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            position    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (event_id, category_id)
        )
    """))

    conn.execute(text("""
        INSERT INTO event_categories (event_id, category_id, position)
        SELECT id, category_id, 0
        FROM events
        WHERE category_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """))

    conn.commit()

result = engine.connect().execute(text("SELECT COUNT(*) FROM event_categories")).scalar()
print(f"Migration complete: event_categories table ready, {result} rows total.")
