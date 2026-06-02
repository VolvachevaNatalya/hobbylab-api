"""
Migration: add is_nationwide boolean column to events table.
Run once: python migrate_add_is_nationwide.py
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
    conn.execute(text(
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS is_nationwide BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    conn.commit()
    print("Migration complete: events.is_nationwide added.")
