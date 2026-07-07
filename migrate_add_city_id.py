"""
Migration: add city_id FK column to organizations and events.

- Adds nullable city_id INTEGER REFERENCES cities(id) to both tables.
- Creates indexes on both city_id columns.
- Does NOT remove the existing city text columns.
- Does NOT backfill any data.
- Does NOT touch any other table or the API.

Idempotent: each ALTER TABLE and CREATE INDEX is guarded with
IF NOT EXISTS / a pre-flight column check so re-running is safe.

Run: .venv/bin/python migrate_add_city_id.py
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

if not os.environ.get("DATABASE_URL"):
    load_dotenv(os.path.join(os.path.dirname(__file__), "app", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL)


def column_exists(conn, table, column):
    row = conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = :t AND column_name = :c
    """), {"t": table, "c": column}).fetchone()
    return row is not None


# ── Snapshot existing data before any change ───────────────────────────────

with engine.connect() as conn:
    org_count_before  = conn.execute(text("SELECT COUNT(*) FROM organizations")).scalar()
    ev_count_before   = conn.execute(text("SELECT COUNT(*) FROM events")).scalar()
    org_city_sample   = conn.execute(
        text("SELECT id, city FROM organizations ORDER BY id")
    ).fetchall()
    ev_city_sample    = conn.execute(
        text("SELECT id, city FROM events ORDER BY id")
    ).fetchall()

print(f"Before migration:")
print(f"  organizations: {org_count_before} rows")
print(f"  events       : {ev_count_before} rows")

# ── Apply schema changes ───────────────────────────────────────────────────

with engine.begin() as conn:
    # 1. organizations.city_id
    if not column_exists(conn, "organizations", "city_id"):
        conn.execute(text("""
            ALTER TABLE organizations
            ADD COLUMN city_id INTEGER REFERENCES cities(id)
        """))
        print("\nAdded organizations.city_id")
    else:
        print("\norganizations.city_id already exists — skipped")

    # 2. events.city_id
    if not column_exists(conn, "events", "city_id"):
        conn.execute(text("""
            ALTER TABLE events
            ADD COLUMN city_id INTEGER REFERENCES cities(id)
        """))
        print("Added events.city_id")
    else:
        print("events.city_id already exists — skipped")

    # 3. Index on organizations.city_id
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_organizations_city_id
        ON organizations (city_id)
    """))
    print("Index idx_organizations_city_id: OK")

    # 4. Index on events.city_id
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_events_city_id
        ON events (city_id)
    """))
    print("Index idx_events_city_id: OK")

# ── Verification ───────────────────────────────────────────────────────────

VERIF_QUERIES = [
    (
        "organizations.city_id column exists",
        """SELECT column_name, data_type, is_nullable
           FROM information_schema.columns
           WHERE table_name='organizations' AND column_name='city_id'""",
    ),
    (
        "events.city_id column exists",
        """SELECT column_name, data_type, is_nullable
           FROM information_schema.columns
           WHERE table_name='events' AND column_name='city_id'""",
    ),
    (
        "FK: organizations.city_id → cities(id)",
        """SELECT tc.constraint_name, kcu.column_name,
                  ccu.table_name AS foreign_table, ccu.column_name AS foreign_column
           FROM information_schema.table_constraints AS tc
           JOIN information_schema.key_column_usage AS kcu
             ON tc.constraint_name = kcu.constraint_name
           JOIN information_schema.constraint_column_usage AS ccu
             ON tc.constraint_name = ccu.constraint_name
           WHERE tc.constraint_type = 'FOREIGN KEY'
             AND tc.table_name = 'organizations'
             AND kcu.column_name = 'city_id'""",
    ),
    (
        "FK: events.city_id → cities(id)",
        """SELECT tc.constraint_name, kcu.column_name,
                  ccu.table_name AS foreign_table, ccu.column_name AS foreign_column
           FROM information_schema.table_constraints AS tc
           JOIN information_schema.key_column_usage AS kcu
             ON tc.constraint_name = kcu.constraint_name
           JOIN information_schema.constraint_column_usage AS ccu
             ON tc.constraint_name = ccu.constraint_name
           WHERE tc.constraint_type = 'FOREIGN KEY'
             AND tc.table_name = 'events'
             AND kcu.column_name = 'city_id'""",
    ),
    (
        "Index idx_organizations_city_id",
        """SELECT indexname, indexdef FROM pg_indexes
           WHERE tablename='organizations' AND indexname='idx_organizations_city_id'""",
    ),
    (
        "Index idx_events_city_id",
        """SELECT indexname, indexdef FROM pg_indexes
           WHERE tablename='events' AND indexname='idx_events_city_id'""",
    ),
    (
        "organizations row count unchanged",
        "SELECT COUNT(*) FROM organizations",
    ),
    (
        "events row count unchanged",
        "SELECT COUNT(*) FROM events",
    ),
    (
        "organizations city_id values (all NULL)",
        "SELECT COUNT(*) FROM organizations WHERE city_id IS NOT NULL",
    ),
    (
        "events city_id values (all NULL)",
        "SELECT COUNT(*) FROM events WHERE city_id IS NOT NULL",
    ),
    (
        "organizations city text column intact",
        "SELECT id, city, city_id FROM organizations ORDER BY id",
    ),
    (
        "events city text column intact",
        "SELECT id, city, city_id FROM events ORDER BY id",
    ),
]

print("\n── Verification ──────────────────────────────────────────────────────────")
all_ok = True
with engine.connect() as conn:
    for label, sql in VERIF_QUERIES:
        rows = conn.execute(text(sql)).fetchall()

        if "row count" in label:
            val = rows[0][0] if rows else 0
            expected = org_count_before if "organizations" in label else ev_count_before
            status = "OK" if val == expected else f"!! changed (expected {expected})"
            if val != expected:
                all_ok = False
            print(f"  {label:<44}: {val}  {status}")

        elif "city_id values" in label:
            val = rows[0][0] if rows else 0
            status = "OK (all NULL)" if val == 0 else f"!! {val} non-NULL rows"
            if val != 0:
                all_ok = False
            print(f"  {label:<44}: {status}")

        elif "column exists" in label or "Index" in label:
            if rows:
                print(f"  {label:<44}: OK  {rows[0]}")
            else:
                print(f"  {label:<44}: !! NOT FOUND")
                all_ok = False

        elif label.startswith("FK:"):
            if rows:
                r = rows[0]
                print(f"  {label:<44}: OK  constraint={r[0]}  {r[1]} → {r[2]}.{r[3]}")
            else:
                print(f"  {label:<44}: !! NOT FOUND")
                all_ok = False

        elif "intact" in label:
            print(f"  {label}:")
            for r in rows:
                print(f"    id={r[0]}  city={r[1]!r}  city_id={r[2]}")

print()
print("Migration successful." if all_ok else "!! One or more checks failed — review output above.")
