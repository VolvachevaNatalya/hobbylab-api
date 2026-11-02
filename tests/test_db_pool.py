"""
Regression tests: the SQLAlchemy engine in app.db.database must be created
with pool_pre_ping=True and pool_recycle=300.

pool_pre_ping prevents stale-connection 500s after Railway closes idle
connections. pool_recycle proactively recycles connections before they hit
Railway's idle timeout (~5 min on free tier).

Tests inspect pool private attributes — stable across SQLAlchemy 1.4.x
and do not require a live database connection.
"""


def test_engine_has_pool_pre_ping():
    """
    Regression: before the fix, pool_pre_ping defaulted to False.
    A stale connection returned from the pool would raise OperationalError
    and produce a 500 on the first request after a quiet period.
    """
    from app.db.database import engine
    assert engine.pool._pre_ping is True, (
        "pool_pre_ping must be True to survive Railway's idle-connection timeouts"
    )


def test_engine_has_pool_recycle():
    """
    pool_recycle=300 ensures connections older than 5 minutes are replaced
    before Railway's PgBouncer closes them.
    """
    from app.db.database import engine
    assert engine.pool._recycle == 300, (
        f"pool_recycle must be 300; got {engine.pool._recycle}"
    )


def test_engine_is_bound_to_database_url():
    """Sanity check: the engine is not None and has a dialect."""
    from app.db.database import engine
    assert engine is not None
    assert engine.dialect is not None
