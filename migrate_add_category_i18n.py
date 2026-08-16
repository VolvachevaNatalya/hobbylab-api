"""
Idempotent migration: add name_en, name_ru, name_he columns to categories
and backfill the 5 production categories with their translations.
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
    # Add columns (idempotent — safe to run multiple times).
    conn.execute(text(
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS name_en VARCHAR(255)"
    ))
    conn.execute(text(
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS name_ru VARCHAR(255)"
    ))
    conn.execute(text(
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS name_he VARCHAR(255)"
    ))

    # Backfill the 5 production categories.
    translations = [
        (1, "Sport",   "Спорт",     "ספורט"),
        (2, "Music",   "Музыка",    "מוזיקה"),
        (3, "Art",     "Искусство", "אמנות"),
        (4, "Theater", "Театр",     "תיאטרון"),
        (5, "Dances",  "Танцы",     "ריקודים"),
    ]
    for cat_id, en, ru, he in translations:
        conn.execute(
            text(
                "UPDATE categories"
                " SET name_en = :en, name_ru = :ru, name_he = :he"
                " WHERE id = :id"
            ),
            {"id": cat_id, "en": en, "ru": ru, "he": he},
        )

print("Migration complete: name_en / name_ru / name_he added and backfilled.")
