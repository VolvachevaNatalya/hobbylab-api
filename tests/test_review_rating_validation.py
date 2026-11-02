"""
Regression tests: review rating must be validated at the API schema level
(Pydantic), not only at the database level (CheckConstraint).

Without schema validation, an out-of-range rating (0, -1, 6, 99…) reaches
the DB, violates the BETWEEN 1 AND 5 check constraint, and produces an
unhandled IntegrityError → HTTP 500.  After the fix, Pydantic rejects
invalid values before they touch the database → HTTP 422.
"""
import pytest

from app.core.security import create_access_token, hash_password
from app.models.organization import Organization
from app.models.review import Review
from app.models.user import User

_REVIEWS_URL = "/reviews/"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="review_val@test.com"):
    u = User(email=email, name="Reviewer", password_hash=hash_password("pw"), status="active")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db):
    o = Organization(name="Review Org", status="active")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_review(db, user_id, org_id, rating=5):
    r = Review(user_id=user_id, organization_id=org_id, rating=rating)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


# ── POST /reviews/ rating validation ─────────────────────────────────────────

def test_create_review_rating_zero_rejected(client, db):
    """
    Regression: rating=0 must return 422 (Pydantic), not 500 (DB constraint).
    """
    user = _make_user(db, "rv_zero@test.com")
    org = _make_org(db)
    resp = client.post(
        _REVIEWS_URL,
        json={"organization_id": org.id, "rating": 0},
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_create_review_rating_negative_rejected(client, db):
    user = _make_user(db, "rv_neg@test.com")
    org = _make_org(db)
    resp = client.post(
        _REVIEWS_URL,
        json={"organization_id": org.id, "rating": -1},
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_create_review_rating_six_rejected(client, db):
    user = _make_user(db, "rv_six@test.com")
    org = _make_org(db)
    resp = client.post(
        _REVIEWS_URL,
        json={"organization_id": org.id, "rating": 6},
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_create_review_rating_large_rejected(client, db):
    user = _make_user(db, "rv_large@test.com")
    org = _make_org(db)
    resp = client.post(
        _REVIEWS_URL,
        json={"organization_id": org.id, "rating": 99},
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_create_review_rating_one_accepted(client, db):
    """Boundary: rating=1 (minimum valid value) must be accepted."""
    user = _make_user(db, "rv_one@test.com")
    org = _make_org(db)
    resp = client.post(
        _REVIEWS_URL,
        json={"organization_id": org.id, "rating": 1},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200


def test_create_review_rating_five_accepted(client, db):
    """Boundary: rating=5 (maximum valid value) must be accepted."""
    user = _make_user(db, "rv_five@test.com")
    org = _make_org(db)
    resp = client.post(
        _REVIEWS_URL,
        json={"organization_id": org.id, "rating": 5},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200


def test_create_review_rating_three_accepted(client, db):
    """Mid-range rating must be accepted."""
    user = _make_user(db, "rv_three@test.com")
    org = _make_org(db)
    resp = client.post(
        _REVIEWS_URL,
        json={"organization_id": org.id, "rating": 3},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200


# ── PUT /reviews/{id} rating validation ──────────────────────────────────────

def test_update_review_rating_zero_rejected(client, db):
    """Update endpoint must also reject out-of-range ratings."""
    user = _make_user(db, "rv_upd_zero@test.com")
    org = _make_org(db)
    review = _make_review(db, user.id, org.id, rating=3)
    resp = client.put(
        f"/reviews/{review.id}",
        json={"rating": 0},
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_update_review_rating_six_rejected(client, db):
    user = _make_user(db, "rv_upd_six@test.com")
    org = _make_org(db)
    review = _make_review(db, user.id, org.id, rating=3)
    resp = client.put(
        f"/reviews/{review.id}",
        json={"rating": 6},
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_update_review_rating_valid_accepted(client, db):
    """Update with a valid in-range rating must succeed."""
    user = _make_user(db, "rv_upd_ok@test.com")
    org = _make_org(db)
    review = _make_review(db, user.id, org.id, rating=3)
    resp = client.put(
        f"/reviews/{review.id}",
        json={"rating": 4},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    assert resp.json()["rating"] == 4
