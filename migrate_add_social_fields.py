"""
Migration: add telegram_url, youtube_url, tiktok_url, whatsapp_url to organizations table.
Run once: python migrate_add_social_fields.py
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
    conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS telegram_url TEXT"))
    conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS youtube_url TEXT"))
    conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS tiktok_url TEXT"))
    conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS whatsapp_url TEXT"))
    conn.commit()
    print("Migration complete: telegram_url, youtube_url, tiktok_url, whatsapp_url added to organizations.")
