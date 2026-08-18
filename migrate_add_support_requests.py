"""
Idempotent migration: create the support_requests table.
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
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS support_requests (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            subject    VARCHAR(255) NOT NULL,
            message    TEXT NOT NULL,
            status     VARCHAR(50) NOT NULL DEFAULT 'new',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
    """))

print("Migration complete: support_requests table created.")
