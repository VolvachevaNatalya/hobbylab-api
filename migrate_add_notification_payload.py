"""
Idempotent migration: add payload TEXT column to notifications table.
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

if not os.environ.get("DATABASE_URL"):
    load_dotenv(os.path.join(os.path.dirname(__file__), "app", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    conn.execute(text(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS payload TEXT"
    ))

print("Migration complete: notifications.payload column added.")
