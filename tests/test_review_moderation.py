"""
Regression tests for the review moderation bypass (P1 security finding).

Root cause: ReviewUpdate accepted a `status` field, which the update endpoint
applied without restriction. Any review owner could set their own review's
status to "active", bypassing moderation.

Fix: `status` was removed from ReviewUpdate. Pydantic v2 silently ignores
unknown fields, so existing clients that happen to send a `status` key receive
a 200 but the field has no effect.
"""
import pytest

from app.core.security import create_access_token, hash_password
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.review import Review
from app.models.user import User

_REVIEWS_URL = "/reviews/"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, is_admin=False):
    u = User(
        email=email,
        name="Test User",
        password_hash=hash_password("pw"),
        status="active",
        is_system_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db):
    o = Organization(name="Moderation Org", status="active")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_review(db, user_id, org_id, rating=5, status="active"):
    r = Review(user_id=user_id, organization_id=org_id, rating=rating, status=status)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


# ── P1 Regression: status field is ignored in ReviewUpdate ────────────────────

def test_owner_cannot_reactivate_moderated_review(client, db):
    """
    Regression: a review that an admin has set to 'pending' must not be
    reactivatable by the review owner via PUT /reviews/{id}.
    """
    user = _make_user(db, "mod_reactivate@test.com")
    org = _make_org(db)
    review = _make_review(db, user.id, org.id, status="pending")

    resp = client.put(
        f"/reviews/{review.id}",
        json={"status": "active"},
        headers=_auth(user.id),
    )

    assert resp.status_code == 200
    db.refresh(review)
    assert review.status == "pending", (
        "status must not change — owner cannot override moderation"
    )


def test_owner_cannot_set_arbitrary_status_string(client, db):
    """
    Regression: arbitrary status strings must not be writable by review owners.
    """
    user = _make_user(db, "mod_arbitrary@test.com")
    org = _make_org(db)
    review = _make_review(db, user.id, org.id, status="active")

    resp = client.put(
        f"/reviews/{review.id}",
        json={"status": "admin_approved"},
        headers=_auth(user.id),
    )

    assert resp.status_code == 200
    db.refresh(review)
    assert review.status == "active", (
        "arbitrary status strings must be ignored"
    )


def test_owner_cannot_suppress_their_own_active_review(client, db):
    """
    Bidirectional check: owner cannot move an active review to 'rejected'
    either (which would effectively delete it from public view).
    """
    user = _make_user(db, "mod_suppress@test.com")
    org = _make_org(db)
    review = _make_review(db, user.id, org.id, status="active")

    resp = client.put(
        f"/reviews/{review.id}",
        json={"status": "rejected"},
        headers=_auth(user.id),
    )

    assert resp.status_code == 200
    db.refresh(review)
    assert review.status == "active", (
        "owner must not be able to self-suppress an active review"
    )


# ── Legitimate edits must remain unaffected ───────────────────────────────────

def test_owner_can_update_rating(client, db):
    """Normal rating update must still work after the fix."""
    user = _make_user(db, "mod_rating@test.com")
    org = _make_org(db)
    review = _make_review(db, user.id, org.id, rating=3, status="active")

    resp = client.put(
        f"/reviews/{review.id}",
        json={"rating": 5},
        headers=_auth(user.id),
    )

    assert resp.status_code == 200
    assert resp.json()["rating"] == 5
    db.refresh(review)
    assert review.rating == 5


def test_owner_can_update_comment(client, db):
    """Normal comment update must still work after the fix."""
    user = _make_user(db, "mod_comment@test.com")
    org = _make_org(db)
    review = _make_review(db, user.id, org.id, status="active")

    resp = client.put(
        f"/reviews/{review.id}",
        json={"comment": "Updated comment"},
        headers=_auth(user.id),
    )

    assert resp.status_code == 200
    assert resp.json()["comment"] == "Updated comment"


def test_updating_rating_does_not_disturb_moderated_status(client, db):
    """
    A legitimate rating update on a moderated review must not side-effect
    the status — the status field is not present in the update payload.
    """
    user = _make_user(db, "mod_nodisturb@test.com")
    org = _make_org(db)
    review = _make_review(db, user.id, org.id, rating=3, status="pending")

    resp = client.put(
        f"/reviews/{review.id}",
        json={"rating": 4},
        headers=_auth(user.id),
    )

    assert resp.status_code == 200
    db.refresh(review)
    assert review.rating == 4
    assert review.status == "pending", (
        "legitimate rating update must not change the moderated status"
    )


# ── Non-owner access control (existing behaviour, sanity check) ───────────────

def test_non_owner_cannot_update_review(client, db):
    """Updating another user's review must return 403."""
    owner = _make_user(db, "mod_owner@test.com")
    other = _make_user(db, "mod_other@test.com")
    org = _make_org(db)
    review = _make_review(db, owner.id, org.id, status="active")

    resp = client.put(
        f"/reviews/{review.id}",
        json={"rating": 1},
        headers=_auth(other.id),
    )

    assert resp.status_code == 403


def test_unauthenticated_cannot_update_review(client, db):
    """No token must return 401."""
    owner = _make_user(db, "mod_noauth@test.com")
    org = _make_org(db)
    review = _make_review(db, owner.id, org.id)

    resp = client.put(f"/reviews/{review.id}", json={"rating": 1})

    assert resp.status_code == 401


# ── POST /reviews/ cannot set status on creation ─────────────────────────────

def test_create_review_status_field_ignored(client, db):
    """
    ReviewCreate has never had a status field, so status in the POST body
    is silently ignored and the review is created with the default ("active").
    """
    user = _make_user(db, "mod_create@test.com")
    org = _make_org(db)

    resp = client.post(
        _REVIEWS_URL,
        json={"organization_id": org.id, "rating": 4, "status": "pending"},
        headers=_auth(user.id),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
