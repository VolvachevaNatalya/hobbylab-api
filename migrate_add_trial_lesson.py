"""
Migration: add trial_lesson_available, trial_lesson_price, trial_lesson_comment to organizations table.
Run once: python migrate_add_trial_lesson.py
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
    conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS trial_lesson_available BOOLEAN NOT NULL DEFAULT FALSE"))
    conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS trial_lesson_price FLOAT"))
    conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS trial_lesson_comment TEXT"))
    conn.commit()
    print("Migration complete: trial_lesson_available, trial_lesson_price, trial_lesson_comment added to organizations.")
