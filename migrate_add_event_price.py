"""
Migration: add price, price_comment to events table.
Run once: python migrate_add_event_price.py
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
    conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS price FLOAT"))
    conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS price_comment TEXT"))
    conn.commit()
    print("Migration complete: price, price_comment added to events.")
