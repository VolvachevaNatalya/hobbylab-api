"""
Data migration: populate city_id on organizations and events.

Pass 1 — exact match: city text = cities.name_en
Pass 2 — alias match: city text in CITY_ALIASES → look up canonical name

The alias list is explicit and exhaustive; no fuzzy or LIKE matching is used.

Does NOT modify the city text columns.
Does NOT touch any other table or the API.

Idempotent: only rows where city_id IS NULL are touched; re-running is safe.

Run: .venv/bin/python migrate_backfill_city_id.py
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

# ── Alias map ──────────────────────────────────────────────────────────────
# Maps historically accepted / colloquial English city names to their
# official CBS name_en as stored in the cities table.
# Only add entries here that are unambiguous and well-established.
# Keys are matched with exact equality — no fuzzy logic.

CITY_ALIASES = {
    "Tel Aviv":        "Tel Aviv-Yafo",   # official CBS name includes Jaffa
    "Jaffa":           "Tel Aviv-Yafo",   # historic district, same municipality
    "Petah Tikva":     "Petah Tiqwa",     # alternate romanisation
    "Petach Tikva":    "Petah Tiqwa",
    "Petach Tikvah":   "Petah Tiqwa",
    "Rishon LeZion":   "Rishon LeTsiyon", # alternate romanisation
    "Rishon Lezion":   "Rishon LeTsiyon",
    "Rishon le-Zion":  "Rishon LeTsiyon",
    "Rehovot":         "Rehovot",         # no-op guard (same spelling)
    "Ramat Gan":       "Ramat Gan",
    "Beersheba":       "Be'er Sheva",     # common English alternate
    "Beer Sheva":      "Be'er Sheva",
    "Beer-Sheva":      "Be'er Sheva",
    "Ashkelon":        "Ashqelon",        # alternate romanisation
    "Askelon":         "Ashqelon",
    "Acre":            "Akko",            # English historic name
    "Akka":            "Akko",
    "Nazareth Illit":  "Nof HaGalil",    # renamed municipality (2019)
    "Upper Nazareth":  "Nof HaGalil",
    "Karmiel":         "Karmi'el",        # alternate romanisation
    "Carmiel":         "Karmi'el",
    "Safed":           "Zefat",           # English historic name
    "Tiberias":        "Teverya",         # English historic name
    "Hadera":          "Hadera",          # same spelling guard
    "Holon":           "Holon",
    "Bat Yam":         "Bat Yam",
    "Netanya":         "Netanya",
}

# ── Backfill helpers ────────────────────────────────────────────────────────

def exact_pass(conn, table):
    """Pass 1: city = cities.name_en (exact)."""
    result = conn.execute(text(f"""
        UPDATE {table} t
        SET city_id = c.id
        FROM cities c
        WHERE t.city_id IS NULL
          AND t.city IS NOT NULL
          AND t.city = c.name_en
    """))
    return result.rowcount


def alias_pass(conn, table, aliases):
    """
    Pass 2: for each alias, update rows whose city equals the alias key
    and whose city_id is still NULL, resolving through the canonical name.
    Returns list of (alias_from, canonical, rows_updated) for non-zero hits.
    """
    used = []
    for alias_from, canonical in aliases.items():
        result = conn.execute(text(f"""
            UPDATE {table} t
            SET city_id = c.id
            FROM cities c
            WHERE t.city_id IS NULL
              AND t.city = :alias_from
              AND c.name_en = :canonical
        """), {"alias_from": alias_from, "canonical": canonical})
        if result.rowcount:
            used.append((alias_from, canonical, result.rowcount))
    return used


def unmatched_rows(conn, table):
    return conn.execute(text(f"""
        SELECT id, city FROM {table}
        WHERE city IS NOT NULL AND city_id IS NULL
        ORDER BY id
    """)).fetchall()


# ── Run migration ──────────────────────────────────────────────────────────

org_alias_hits = []
ev_alias_hits  = []

with engine.begin() as conn:
    print("Pass 1 — exact match …")
    org_exact   = exact_pass(conn, "organizations")
    ev_exact    = exact_pass(conn, "events")

    print("Pass 2 — alias match …")
    org_alias_hits = alias_pass(conn, "organizations", CITY_ALIASES)
    ev_alias_hits  = alias_pass(conn, "events",        CITY_ALIASES)

    org_unmatched = unmatched_rows(conn, "organizations")
    ev_unmatched  = unmatched_rows(conn, "events")

org_alias_total = sum(n for _, _, n in org_alias_hits)
ev_alias_total  = sum(n for _, _, n in ev_alias_hits)

print()
print(f"Organizations — exact matches  : {org_exact}")
print(f"Organizations — alias matches  : {org_alias_total}")
print(f"Organizations — total updated  : {org_exact + org_alias_total}")
print()
print(f"Events        — exact matches  : {ev_exact}")
print(f"Events        — alias matches  : {ev_alias_total}")
print(f"Events        — total updated  : {ev_exact + ev_alias_total}")

all_alias_hits = org_alias_hits + ev_alias_hits
if all_alias_hits:
    print("\nAliases used:")
    for alias_from, canonical, n in all_alias_hits:
        print(f"  {alias_from!r:<26} → {canonical!r}  ({n} row{'s' if n != 1 else ''})")
else:
    print("\nAliases used: none")

if org_unmatched:
    print(f"\nOrganizations still unmatched ({len(org_unmatched)}) — city_id left NULL:")
    for row_id, city in org_unmatched:
        print(f"  id={row_id}  city={city!r}")
else:
    print("\nOrganizations: all non-NULL city values matched.")

if ev_unmatched:
    print(f"\nEvents still unmatched ({len(ev_unmatched)}) — city_id left NULL:")
    for row_id, city in ev_unmatched:
        print(f"  id={row_id}  city={city!r}")
else:
    print("Events: all non-NULL city values matched (or all were NULL).")

# ── Verification ───────────────────────────────────────────────────────────

print()
print("── Verification ──────────────────────────────────────────────────────────")

with engine.connect() as conn:
    print("\n  organization id | city | city_id | cities.name_en")
    print(f"  {'id':<6} {'city':<24} {'city_id':<10} cities.name_en")
    print("  " + "-" * 64)
    for row in conn.execute(text("""
        SELECT o.id, o.city, o.city_id, c.name_en
        FROM organizations o
        LEFT JOIN cities c ON c.id = o.city_id
        ORDER BY o.id
    """)).fetchall():
        oid, city, city_id, name_en = row
        print(f"  {oid:<6} {(city or 'NULL'):<24} {str(city_id or 'NULL'):<10} {name_en or 'NULL'}")

    print("\n  event id | city | city_id | cities.name_en")
    print(f"  {'id':<6} {'city':<24} {'city_id':<10} cities.name_en")
    print("  " + "-" * 64)
    for row in conn.execute(text("""
        SELECT e.id, e.city, e.city_id, c.name_en
        FROM events e
        LEFT JOIN cities c ON c.id = e.city_id
        ORDER BY e.id
    """)).fetchall():
        eid, city, city_id, name_en = row
        print(f"  {eid:<6} {(city or 'NULL'):<24} {str(city_id or 'NULL'):<10} {name_en or 'NULL'}")

    print("\n  Incorrect matches (city_id set but city ≠ cities.name_en and city not an alias):")
    bad = []
    for table, col in [("organizations", "o"), ("events", "e")]:
        rows = conn.execute(text(f"""
            SELECT {col}.id, {col}.city, {col}.city_id, c.name_en
            FROM {table} {col}
            JOIN cities c ON c.id = {col}.city_id
            WHERE {col}.city <> c.name_en
        """)).fetchall()
        for r in rows:
            # A mismatch is acceptable only when the city value is a known alias
            if r[1] not in CITY_ALIASES or CITY_ALIASES[r[1]] != r[3]:
                bad.append((table, r))
    if bad:
        print("  !! INCORRECT MATCHES:")
        for table, r in bad:
            print(f"    {table} id={r[0]}  city={r[1]!r}  city_id={r[2]}  name_en={r[3]!r}")
    else:
        print("  OK — no incorrect matches.")

print()
print("Migration complete.")
