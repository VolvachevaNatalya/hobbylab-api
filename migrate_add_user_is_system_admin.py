"""
Idempotent migration: add is_system_admin BOOLEAN column to users table.

All existing rows will have is_system_admin = false (enforced by the DEFAULT).
No user is promoted to system admin by this script.

Run once on the production database. Safe to re-run — ADD COLUMN IF NOT EXISTS
is a no-op when the column already exists.

Usage:
    python migrate_add_user_is_system_admin.py
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
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS"
        " is_system_admin BOOLEAN NOT NULL DEFAULT false"
    ))
    conn.commit()

print("Migration complete: users.is_system_admin column is present.")
