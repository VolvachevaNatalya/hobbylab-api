"""
Migration: create organization_categories table.
No backfill needed — organizations never had a category_id column.
Safe to run more than once — CREATE TABLE IF NOT EXISTS.
Run: python migrate_add_organization_categories.py
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
        CREATE TABLE IF NOT EXISTS organization_categories (
            organization_id  INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            category_id      INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            position         INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (organization_id, category_id)
        )
    """))
    conn.commit()

print("Migration complete: organization_categories table ready.")
