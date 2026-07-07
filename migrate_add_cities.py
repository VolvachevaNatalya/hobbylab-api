"""
Migration: create cities reference table.

Idempotent — safe to run more than once (CREATE TABLE IF NOT EXISTS,
CREATE UNIQUE INDEX IF NOT EXISTS, CREATE INDEX IF NOT EXISTS).

Does NOT seed rows.
Does NOT add city_id columns to other tables.

Run: python migrate_add_cities.py
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Mirror the same env-loading logic as app/db/database.py:
# use the environment variable if already set (Railway/CI),
# otherwise fall back to app/.env for local development.
if not os.environ.get("DATABASE_URL"):
    load_dotenv(os.path.join(os.path.dirname(__file__), "app", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cities (
            id          SERIAL PRIMARY KEY,
            name_he     VARCHAR(100) NOT NULL,
            name_en     VARCHAR(100) NOT NULL,
            name_ru     VARCHAR(100) NOT NULL,
            latitude    FLOAT,
            longitude   FLOAT,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE
        )
    """))

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS cities_name_he_idx
        ON cities (name_he)
    """))

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS cities_name_en_idx
        ON cities (name_en)
    """))

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS cities_name_ru_idx
        ON cities (name_ru)
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS cities_is_active_idx
        ON cities (is_active)
    """))

    conn.commit()

with engine.connect() as conn:
    row = conn.execute(text("""
        SELECT
            column_name,
            data_type,
            character_maximum_length,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_name = 'cities'
        ORDER BY ordinal_position
    """)).fetchall()

    indexes = conn.execute(text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'cities'
        ORDER BY indexname
    """)).fetchall()

print("\ncities table columns:")
print(f"  {'column':<12} {'type':<20} {'nullable':<10} {'default'}")
print("  " + "-" * 60)
for col_name, data_type, char_len, nullable, default in row:
    type_display = f"{data_type}({char_len})" if char_len else data_type
    print(f"  {col_name:<12} {type_display:<20} {nullable:<10} {default or ''}")

print("\ncities indexes:")
for idx_name, idx_def in indexes:
    print(f"  {idx_name}")
    print(f"    {idx_def}")

print("\nMigration complete: cities table ready.")
