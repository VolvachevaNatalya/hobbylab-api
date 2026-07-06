"""
Migration: create organization_categories table and backfill from classes.

Organizations have no category_id column. Their categories are derived from
the classes they offer: any category assigned to a class is attributed to
the owning organization.

Step 1: CREATE TABLE IF NOT EXISTS (idempotent).
Step 2: INSERT DISTINCT (org, category) pairs from classes at position 0.
        ON CONFLICT DO NOTHING makes this safe to run multiple times.

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

    conn.execute(text("""
        INSERT INTO organization_categories (organization_id, category_id, position)
        SELECT DISTINCT organization_id, category_id, 0
        FROM classes
        WHERE category_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """))

    conn.commit()

with engine.connect() as conn:
    total = conn.execute(text("SELECT COUNT(*) FROM organization_categories")).scalar()
    print(f"Migration complete: organization_categories table ready, {total} rows total.")
