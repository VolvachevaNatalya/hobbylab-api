"""
PostgreSQL-only concurrency integration test for provider unlink safety.

SKIP CONDITIONS
---------------
This test is skipped unless TEST_DATABASE_URL is set to a PostgreSQL connection
string.  It must NEVER run against the deployed Railway database.

To run locally:
    createdb hobbylab_test
    TEST_DATABASE_URL=postgresql://localhost/hobbylab_test pytest tests/test_concurrent_providers_pg.py -v

WHAT THIS TESTS
---------------
Race condition: two concurrent DELETE /me/auth-providers requests for a user that
has exactly two providers.  Each request reads the total count before the other
completes.  Without SELECT...FOR UPDATE, both see count=2, both proceed, and both
delete their row — leaving the account with 0 providers (permanently locked out).

With SELECT...FOR UPDATE on all provider rows for the user, the second transaction
blocks until the first commits.  After the first completes, the second sees count=1
and returns 400 "Cannot remove the last sign-in method."

WHY SQLITE CANNOT TEST THIS
----------------------------
SQLite ignores with_for_update() — it has no row-level locking.  Concurrent writes
are serialized by the GIL + SQLite's global write lock, but that is a different
mechanism and does not prove the PostgreSQL FOR UPDATE path works.
"""
import os
import threading
import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL.startswith("postgresql"),
    reason=(
        "Requires TEST_DATABASE_URL=postgresql://user:pass@localhost/hobbylab_test. "
        "Never set this to the Railway production database."
    ),
)


@pytest.fixture(scope="module")
def pg_engine():
    from sqlalchemy import create_engine
    from app.db.database import Base
    import app.models.user               # noqa: F401
    import app.models.user_auth_provider  # noqa: F401

    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=pg_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


def _make_pg_user(session, email):
    from app.models.user import User
    u = User(email=email, name="PG Test", password_hash=None, status="active")
    session.add(u)
    session.flush()
    return u


def _add_pg_provider(session, user_id, provider, sub):
    from app.models.user_auth_provider import UserAuthProvider
    ap = UserAuthProvider(user_id=user_id, provider=provider, provider_user_id=sub)
    session.add(ap)
    session.flush()
    return ap


def test_concurrent_unlink_cannot_remove_all_providers(pg_engine):
    """
    Two threads concurrently unlink the user's two providers.
    PostgreSQL row locking ensures exactly one succeeds; the other sees count=1
    and returns 400.  After both complete, exactly 1 provider must remain.

    VERIFIED: This test requires PostgreSQL and real concurrent DB connections.
    It is NOT equivalent to the SQLite serial test in test_auth_providers.py.
    """
    from sqlalchemy.orm import sessionmaker
    from app.models.user import User
    from app.models.user_auth_provider import UserAuthProvider
    from app.api.providers import unlink_auth_provider
    from fastapi import HTTPException

    Session = sessionmaker(bind=pg_engine)

    # Setup: create user + 2 providers
    setup_session = Session()
    u = _make_pg_user(setup_session, "pg_concurrent@test.com")
    ap1 = _add_pg_provider(setup_session, u.id, "google", "gsub_pg_concurrent")
    ap2 = _add_pg_provider(setup_session, u.id, "facebook", "fb_pg_concurrent")
    setup_session.commit()
    user_id = u.id
    ap1_id = ap1.id
    ap2_id = ap2.id
    setup_session.close()

    results = {}
    barrier = threading.Barrier(2)

    def _try_unlink(provider_id, thread_name):
        session = Session()
        try:
            # Re-fetch user so each thread has its own session-bound instance
            user = session.query(User).filter_by(id=user_id).first()
            barrier.wait()  # synchronize to maximize concurrency
            try:
                unlink_auth_provider(
                    provider_id=provider_id,
                    current_user=user,
                    db=session,
                )
                results[thread_name] = "success"
            except HTTPException as e:
                results[thread_name] = e.status_code
        finally:
            session.close()

    t1 = threading.Thread(target=_try_unlink, args=(ap1_id, "t1"))
    t2 = threading.Thread(target=_try_unlink, args=(ap2_id, "t2"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one thread must have succeeded; the other must have been blocked
    verify_session = Session()
    remaining = (
        verify_session.query(UserAuthProvider)
        .filter_by(user_id=user_id)
        .count()
    )
    verify_session.close()

    success_count = sum(1 for v in results.values() if v == "success")
    blocked_count = sum(1 for v in results.values() if v == 400)

    assert remaining == 1, (
        f"Expected 1 provider to remain, found {remaining}. "
        f"Thread results: {results}. This may indicate a locking failure."
    )
    assert success_count == 1, f"Expected exactly 1 success, got: {results}"
    assert blocked_count == 1, f"Expected exactly 1 blocked (400), got: {results}"

    # Cleanup
    cleanup_session = Session()
    cleanup_session.query(UserAuthProvider).filter_by(user_id=user_id).delete()
    cleanup_session.query(User).filter_by(id=user_id).delete()
    cleanup_session.commit()
    cleanup_session.close()
