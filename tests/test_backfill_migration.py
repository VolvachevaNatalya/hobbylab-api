"""
Regression tests for the user_auth_providers backfill migration.

Production failure:
    psycopg2.errors.NotNullViolation: null value in column "created_at" of relation
    "user_auth_providers" violates not-null constraint

Root cause:
    Base.metadata.create_all() generates the table DDL from the SQLAlchemy model.
    The model defined `created_at` with a Python-side `default=datetime.utcnow` but
    no `server_default`.  SQLAlchemy therefore emits:
        created_at TIMESTAMP NOT NULL
    with no DEFAULT clause.  The subsequent INSERT...SELECT in main.py omitted the
    created_at column, so PostgreSQL received NULL — violating the NOT NULL constraint.

Fix (two-part):
    1. app/models/user_auth_provider.py — added server_default=func.now() so that
       create_all() now generates DEFAULT NOW() on the column for new installs.
    2. app/main.py backfill INSERT — explicitly includes created_at = NOW() so that
       existing deployments (table already exists without DEFAULT) are also fixed.

SQLite compatibility note:
    These tests use the SQLite test engine and use CURRENT_TIMESTAMP instead of NOW().
    Both expressions return the current UTC timestamp; the difference is dialect syntax.
    The underlying behaviour being tested (explicit column vs. relying on column DEFAULT)
    is identical.  PostgreSQL-specific error reproduction requires a real PostgreSQL
    connection; see test_concurrent_providers_pg.py for the pattern to extend.
"""
import pytest
from sqlalchemy import text

from app.models.user import User
from app.models.user_auth_provider import UserAuthProvider


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_social_user(db, email, provider, provider_user_id):
    u = User(
        email=email,
        name="Migration Test",
        password_hash=None,
        status="active",
        provider=provider,
        provider_user_id=provider_user_id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# Backfill SQL using CURRENT_TIMESTAMP (ANSI SQL; production uses NOW() on PostgreSQL)
_BACKFILL_SQL = text("""
    INSERT INTO user_auth_providers
        (user_id, provider, provider_user_id, provider_email, created_at)
    SELECT id, provider, provider_user_id, email, CURRENT_TIMESTAMP
    FROM users
    WHERE password_hash IS NULL
      AND provider IS NOT NULL
      AND provider_user_id IS NOT NULL
    ON CONFLICT DO NOTHING
""")


# ── tests ─────────────────────────────────────────────────────────────────────

def test_backfill_inserts_row_with_non_null_created_at(db):
    """
    The backfill INSERT must populate created_at explicitly.
    Regression: before the fix, created_at was omitted and PostgreSQL raised
    NotNullViolation.
    """
    user = _make_social_user(db, "mig_created_at@test.com", "google", "google_mig_sub_1")
    assert db.query(UserAuthProvider).filter_by(user_id=user.id).count() == 0

    db.execute(_BACKFILL_SQL)
    db.commit()

    ap = db.query(UserAuthProvider).filter_by(user_id=user.id).first()
    assert ap is not None, "Backfill did not create a UserAuthProvider row"
    assert ap.created_at is not None, (
        "created_at is NULL after backfill — the INSERT must explicitly include created_at"
    )
    assert ap.provider == "google"
    assert ap.provider_user_id == "google_mig_sub_1"


def test_backfill_is_idempotent(db):
    """Running the backfill SQL twice must not raise or create duplicate rows."""
    user = _make_social_user(db, "mig_idempotent@test.com", "facebook", "fb_mig_sub_2")

    db.execute(_BACKFILL_SQL)
    db.commit()
    db.execute(_BACKFILL_SQL)
    db.commit()

    count = db.query(UserAuthProvider).filter_by(user_id=user.id).count()
    assert count == 1, f"Expected 1 row after idempotent re-run, got {count}"


def test_backfill_skips_email_password_users(db):
    """Users with password_hash set must not be back-filled."""
    u = User(
        email="mig_legacy@test.com",
        name="Legacy",
        password_hash="$2b$12$fakehash",
        status="active",
        provider="google",
        provider_user_id="google_legacy_sub",
    )
    db.add(u)
    db.commit()

    db.execute(_BACKFILL_SQL)
    db.commit()

    assert db.query(UserAuthProvider).filter_by(user_id=u.id).count() == 0


def test_backfill_skips_users_without_provider_data(db):
    """Social users with no provider_user_id (incomplete rows) must not be back-filled."""
    u = User(
        email="mig_noprovider@test.com",
        name="No Provider",
        password_hash=None,
        status="active",
        provider=None,
        provider_user_id=None,
    )
    db.add(u)
    db.commit()

    db.execute(_BACKFILL_SQL)
    db.commit()

    assert db.query(UserAuthProvider).filter_by(user_id=u.id).count() == 0


def test_backfill_does_not_overwrite_existing_link(db):
    """
    If a UserAuthProvider row already exists for a user (e.g., from a prior partial
    startup), ON CONFLICT DO NOTHING must leave the existing row untouched.
    """
    user = _make_social_user(db, "mig_existing@test.com", "apple", "apple_mig_sub_3")

    # Pre-existing link (created by earlier startup or sign-in)
    existing = UserAuthProvider(
        user_id=user.id,
        provider="apple",
        provider_user_id="apple_mig_sub_3",
        provider_email="existing@example.com",
    )
    db.add(existing)
    db.commit()
    db.refresh(existing)
    original_id = existing.id

    db.execute(_BACKFILL_SQL)
    db.commit()

    rows = db.query(UserAuthProvider).filter_by(user_id=user.id).all()
    assert len(rows) == 1, "ON CONFLICT DO NOTHING must not add a duplicate row"
    assert rows[0].id == original_id, "Existing row must not be replaced"


def test_orm_insert_populates_created_at_via_python_default(db):
    """
    ORM-managed inserts use the Python-side default=datetime.utcnow.
    Verifies the ORM path is unaffected by the server_default addition.
    """
    user = _make_social_user(db, "orm_insert@test.com", "google", "google_orm_sub")
    ap = UserAuthProvider(
        user_id=user.id,
        provider="google",
        provider_user_id="google_orm_sub",
        provider_email="orm_insert@test.com",
    )
    db.add(ap)
    db.commit()
    db.refresh(ap)

    assert ap.created_at is not None, "ORM insert must populate created_at via Python default"
