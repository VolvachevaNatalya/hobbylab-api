"""
Regression tests for DELETE /me (account deletion).

Strategy: soft-delete
  - Sets user.status = 'deleted'
  - Bumps token_version (invalidates all JWTs/refresh tokens)
  - Deletes all user_auth_providers rows (prevents social re-login)
  - Leaves reviews, conversations, messages intact (they CASCADE if hard-deleted,
    destroying other users' data)
  - 409 if user is sole owner of any organisation
  - Idempotent: second call with same (now-invalid) token returns 401 or 403,
    not 500
"""
from app.core.security import create_access_token
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.models.user_auth_provider import UserAuthProvider


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_social_user(db, email, provider="google", provider_user_id=None, name="Test User"):
    provider_user_id = provider_user_id or f"{provider}_{email}"
    u = User(
        email=email,
        name=name,
        password_hash=None,
        status="active",
        provider=provider,
        provider_user_id=provider_user_id,
        token_version=0,
    )
    db.add(u)
    db.flush()
    ap = UserAuthProvider(
        user_id=u.id,
        provider=provider,
        provider_user_id=provider_user_id,
        provider_email=email,
    )
    db.add(ap)
    db.commit()
    db.refresh(u)
    return u


def _auth(user):
    tv = user.token_version or 0
    token = create_access_token({"user_id": user.id, "tv": tv})
    return {"Authorization": f"Bearer {token}"}


# ── tests ─────────────────────────────────────────────────────────────────────

def test_delete_account_returns_204(client, db):
    user = _make_social_user(db, "del_204@test.com")
    resp = client.delete("/me", headers=_auth(user))
    assert resp.status_code == 204


def test_delete_account_sets_status_deleted(client, db):
    user = _make_social_user(db, "del_status@test.com")
    original_id = user.id
    client.delete("/me", headers=_auth(user))
    db.refresh(user)
    assert user.status == "deleted"
    # Email must be anonymized so the address is free for future re-registration.
    assert user.email == f"deleted_{original_id}@deleted.local"


def test_delete_account_bumps_token_version(client, db):
    user = _make_social_user(db, "del_tv@test.com")
    original_tv = user.token_version or 0
    client.delete("/me", headers=_auth(user))
    db.refresh(user)
    assert user.token_version == original_tv + 1


def test_delete_account_removes_auth_providers(client, db):
    user = _make_social_user(db, "del_providers@test.com")
    assert db.query(UserAuthProvider).filter_by(user_id=user.id).count() == 1

    client.delete("/me", headers=_auth(user))

    assert db.query(UserAuthProvider).filter_by(user_id=user.id).count() == 0


def test_delete_account_invalidates_old_token(client, db):
    """After deletion, the original token must be rejected (account not active / tv bumped)."""
    user = _make_social_user(db, "del_invalidate@test.com")
    headers = _auth(user)  # token captured before deletion

    client.delete("/me", headers=headers)

    # Same token reused — user.status == "deleted" → 403
    resp = client.get("/me", headers=headers)
    assert resp.status_code in (401, 403)


def test_delete_account_requires_auth(client, db):
    resp = client.delete("/me")
    assert resp.status_code == 401


def test_delete_account_sole_owner_blocked(client, db):
    """User who is the sole owner of an org must receive 409."""
    user = _make_social_user(db, "del_sole_owner@test.com")

    org = Organization(name="Only Mine", status="active")
    db.add(org)
    db.flush()
    membership = OrganizationUser(organization_id=org.id, user_id=user.id, role="owner")
    db.add(membership)
    db.commit()

    resp = client.delete("/me", headers=_auth(user))
    assert resp.status_code == 409
    assert "sole owner" in resp.json()["detail"].lower()

    # User must NOT have been soft-deleted
    db.refresh(user)
    assert user.status == "active"


def test_delete_account_allowed_when_co_owner_exists(client, db):
    """User can delete their account if at least one other owner exists for each org."""
    user = _make_social_user(db, "del_co_owner@test.com")
    co_owner = _make_social_user(db, "co_owner@test.com", provider_user_id="co_google_co")

    org = Organization(name="Shared Org", status="active")
    db.add(org)
    db.flush()
    db.add(OrganizationUser(organization_id=org.id, user_id=user.id, role="owner"))
    db.add(OrganizationUser(organization_id=org.id, user_id=co_owner.id, role="owner"))
    db.commit()

    resp = client.delete("/me", headers=_auth(user))
    assert resp.status_code == 204

    db.refresh(user)
    assert user.status == "deleted"


def test_delete_account_non_owner_role_not_blocked(client, db):
    """User with 'admin' (non-owner) role in an org is not blocked from deleting."""
    user = _make_social_user(db, "del_admin_role@test.com")
    owner = _make_social_user(db, "org_owner@test.com", provider_user_id="google_orgowner")

    org = Organization(name="Admin Org", status="active")
    db.add(org)
    db.flush()
    db.add(OrganizationUser(organization_id=org.id, user_id=owner.id, role="owner"))
    db.add(OrganizationUser(organization_id=org.id, user_id=user.id, role="admin"))
    db.commit()

    resp = client.delete("/me", headers=_auth(user))
    assert resp.status_code == 204


def test_delete_account_idempotent_already_deleted(client, db):
    """
    If a user is already deleted, the stale token is rejected with 401/403.
    Verifies no server crash on second attempt.
    """
    user = _make_social_user(db, "del_idem@test.com")
    headers = _auth(user)

    client.delete("/me", headers=headers)

    # Second call with same (now-invalid) token
    resp = client.delete("/me", headers=headers)
    assert resp.status_code in (401, 403)
