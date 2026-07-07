"""
Seed the cities table from cities_seed.json.

Idempotent: uses INSERT … ON CONFLICT DO NOTHING on all three unique
name columns, so re-running is safe.

Does NOT modify any other table.
Does NOT add city_id columns anywhere.
Does NOT touch the API.

Run: .venv/bin/python migrate_seed_cities.py
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

if not os.environ.get("DATABASE_URL"):
    load_dotenv(os.path.join(os.path.dirname(__file__), "app", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

SEED_FILE = Path(__file__).parent / "cities_seed.json"

# ── Load seed ──────────────────────────────────────────────────────────────

with open(SEED_FILE, encoding="utf-8") as f:
    cities = json.load(f)

print(f"Loaded {len(cities)} entries from {SEED_FILE.name}")

# ── Insert ─────────────────────────────────────────────────────────────────

engine = create_engine(DATABASE_URL)

INSERT_SQL = text("""
    INSERT INTO cities (name_he, name_en, name_ru)
    VALUES (:name_he, :name_en, :name_ru)
    ON CONFLICT DO NOTHING
""")

with engine.begin() as conn:
    count_before = conn.execute(text("SELECT COUNT(*) FROM cities")).scalar()

    result = conn.execute(INSERT_SQL, cities)
    inserted = result.rowcount

    count_after = conn.execute(text("SELECT COUNT(*) FROM cities")).scalar()

print()
print(f"Rows before insertion : {count_before}")
print(f"Rows inserted         : {inserted}")
print(f"Rows after insertion  : {count_after}")

# ── Verification ───────────────────────────────────────────────────────────

VERIF_QUERIES = [
    (
        "Total row count",
        "SELECT COUNT(*) FROM cities",
    ),
    (
        "Duplicate name_he",
        "SELECT name_he, COUNT(*) AS n FROM cities GROUP BY name_he HAVING COUNT(*) > 1",
    ),
    (
        "Duplicate name_en",
        "SELECT name_en, COUNT(*) AS n FROM cities GROUP BY name_en HAVING COUNT(*) > 1",
    ),
    (
        "Duplicate name_ru",
        "SELECT name_ru, COUNT(*) AS n FROM cities GROUP BY name_ru HAVING COUNT(*) > 1",
    ),
    (
        "Rows with empty name_he",
        "SELECT COUNT(*) FROM cities WHERE name_he = '' OR name_he IS NULL",
    ),
    (
        "Rows with empty name_en",
        "SELECT COUNT(*) FROM cities WHERE name_en = '' OR name_en IS NULL",
    ),
    (
        "Rows with empty name_ru",
        "SELECT COUNT(*) FROM cities WHERE name_ru = '' OR name_ru IS NULL",
    ),
    (
        "Sample rows (10)",
        "SELECT id, name_he, name_en, name_ru FROM cities ORDER BY id LIMIT 10",
    ),
]

print()
print("── Verification ──────────────────────────────────────────────────────────")
with engine.connect() as conn:
    for label, sql in VERIF_QUERIES:
        rows = conn.execute(text(sql)).fetchall()
        if label.startswith("Total") or label.startswith("Rows with"):
            val = rows[0][0] if rows else 0
            status = ""
            if "empty" in label and val > 0:
                status = "  !! PROBLEM"
            elif "Total" in label and val != len(cities):
                status = f"  !! expected {len(cities)}"
            print(f"  {label:<30}: {val}{status}")
        elif label.startswith("Duplicate"):
            if rows:
                print(f"  {label:<30}: !! {len(rows)} collisions")
                for r in rows:
                    print(f"      {r[0]!r}  count={r[1]}")
            else:
                print(f"  {label:<30}: OK (none)")
        elif label.startswith("Sample"):
            print(f"\n  {label}:")
            print(f"    {'id':<6} {'name_he':<38} {'name_en':<36} name_ru")
            print("    " + "-" * 110)
            for r in rows:
                print(f"    {r[0]:<6} {r[1]:<38} {r[2]:<36} {r[3]}")

print()
print("Seeding complete.")
