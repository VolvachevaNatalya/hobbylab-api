"""
Regression tests: account deletion followed by re-registration with the same
social identity (Google, Facebook, Apple — including Apple private relay).

Product requirements verified:
  1. Deletion invalidates all existing sessions and social provider links.
  2. The deleted account cannot be accessed or restored through social login.
  3. Re-registering with the same social identity creates a NEW account (new ID).
  4. The new account inherits none of the deleted account's data.
  5. Works for Google, Facebook, Apple (with and without email).
  6. Old access tokens remain invalid after re-registration.
  7. Social identities are never merged solely by email match.
  8. Deleted accounts without prior email anonymization are handled via lazy migration.
"""
import os
from unittest.mock import patch

import pytest

from app.core.security import create_access_token
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


def _google_login(client, sub, email, name="Returning User"):
    id_info = {
        "sub": sub,
        "email": email,
        "name": name,
        "email_verified": True,
    }
    with patch("app.api.auth.os.getenv", return_value="fake-client-id"), \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=id_info):
        return client.post("/auth/google-login", json={"id_token": "fake-token"})


def _facebook_login(client, fb_id, email, name="Returning User"):
    fb_data = {"id": fb_id, "email": email, "name": name}
    with patch("app.api.auth._validate_facebook_token", return_value=fb_data):
        return client.post("/auth/facebook-login", json={"access_token": "fake-token"})


def _apple_login(client, apple_sub, email="", name=""):
    claims = {
        "sub": apple_sub,
        "email": email,
        "email_verified": True if email else False,
        "nonce": "fake-nonce-hash",
    }
    with patch("app.api.auth._validate_apple_token", return_value=claims):
        return client.post(
            "/auth/apple-login",
            json={"id_token": "fake-token", "nonce": "fake-nonce"},
        )


# ── Google ────────────────────────────────────────────────────────────────────

def test_google_reregister_after_delete_creates_new_account(client, db):
    """Delete a Google account then sign in again — must get a fresh account."""
    google_sub = "g_sub_rereg_001"
    email = "rereg_google@test.com"

    user = _make_social_user(db, email, provider="google", provider_user_id=google_sub)
    old_id = user.id
    old_headers = _auth(user)

    resp = client.delete("/me", headers=old_headers)
    assert resp.status_code == 204

    # Email must have been anonymized
    db.refresh(user)
    assert user.email == f"deleted_{old_id}@deleted.local"

    # Re-register with the same Google identity
    resp2 = _google_login(client, google_sub, email)
    assert resp2.status_code == 200, resp2.text
    tokens = resp2.json()

    # New tokens must refer to a different user
    new_resp = client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert new_resp.status_code == 200
    assert new_resp.json()["id"] != old_id, "New account must have a different user ID"
    assert new_resp.json()["email"] == email


def test_google_reregister_old_token_still_invalid(client, db):
    """Old pre-deletion access token must remain rejected after re-registration."""
    google_sub = "g_sub_rereg_002"
    email = "rereg_oldtoken@test.com"

    user = _make_social_user(db, email, provider="google", provider_user_id=google_sub)
    old_headers = _auth(user)

    client.delete("/me", headers=old_headers)
    _google_login(client, google_sub, email)  # re-register

    # Old token still rejected — deleted user's status/token_version blocks it
    resp = client.get("/me", headers=old_headers)
    assert resp.status_code in (401, 403)


# ── Facebook ──────────────────────────────────────────────────────────────────

def test_facebook_reregister_after_delete_creates_new_account(client, db):
    fb_id = "fb_id_rereg_001"
    email = "rereg_facebook@test.com"

    user = _make_social_user(db, email, provider="facebook", provider_user_id=fb_id)
    old_id = user.id
    old_headers = _auth(user)

    resp = client.delete("/me", headers=old_headers)
    assert resp.status_code == 204

    db.refresh(user)
    assert user.email == f"deleted_{old_id}@deleted.local"

    resp2 = _facebook_login(client, fb_id, email)
    assert resp2.status_code == 200, resp2.text
    tokens = resp2.json()

    new_resp = client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert new_resp.status_code == 200
    assert new_resp.json()["id"] != old_id
    assert new_resp.json()["email"] == email


def test_facebook_reregister_old_token_still_invalid(client, db):
    fb_id = "fb_id_rereg_002"
    email = "rereg_fb_old@test.com"

    user = _make_social_user(db, email, provider="facebook", provider_user_id=fb_id)
    old_headers = _auth(user)

    client.delete("/me", headers=old_headers)
    _facebook_login(client, fb_id, email)

    resp = client.get("/me", headers=old_headers)
    assert resp.status_code in (401, 403)


# ── Apple (with email) ────────────────────────────────────────────────────────

def test_apple_reregister_after_delete_creates_new_account(client, db):
    apple_sub = "apple_sub_rereg_001"
    email = "rereg_apple@test.com"

    user = _make_social_user(db, email, provider="apple", provider_user_id=apple_sub)
    old_id = user.id
    old_headers = _auth(user)

    resp = client.delete("/me", headers=old_headers)
    assert resp.status_code == 204

    db.refresh(user)
    assert user.email == f"deleted_{old_id}@deleted.local"

    resp2 = _apple_login(client, apple_sub, email)
    assert resp2.status_code == 200, resp2.text
    tokens = resp2.json()

    new_resp = client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert new_resp.status_code == 200
    assert new_resp.json()["id"] != old_id


def test_apple_reregister_old_token_still_invalid(client, db):
    apple_sub = "apple_sub_rereg_002"
    email = "rereg_apple_old@test.com"

    user = _make_social_user(db, email, provider="apple", provider_user_id=apple_sub)
    old_headers = _auth(user)

    client.delete("/me", headers=old_headers)
    _apple_login(client, apple_sub, email)

    resp = client.get("/me", headers=old_headers)
    assert resp.status_code in (401, 403)


# ── Apple (private relay / no email) ──────────────────────────────────────────

def test_apple_private_relay_reregister_after_delete(client, db):
    """Apple user with no email (private relay) can re-register after deletion."""
    apple_sub = "apple_sub_noemail_001"
    # Simulate the noemail.local fallback that the registration code uses
    fallback_email = f"apple_{apple_sub}@noemail.local"

    user = _make_social_user(db, fallback_email, provider="apple", provider_user_id=apple_sub)
    old_id = user.id
    old_headers = _auth(user)

    resp = client.delete("/me", headers=old_headers)
    assert resp.status_code == 204

    db.refresh(user)
    assert user.email == f"deleted_{old_id}@deleted.local"

    # Re-register with the same Apple identity but no email
    resp2 = _apple_login(client, apple_sub, email="")
    assert resp2.status_code == 200, resp2.text
    tokens = resp2.json()

    new_resp = client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert new_resp.status_code == 200
    assert new_resp.json()["id"] != old_id


# ── Cross-provider isolation ──────────────────────────────────────────────────

def test_deleted_account_not_restored_by_different_provider(client, db):
    """
    Registering with a different provider that shares the same email must not
    restore a deleted account.  A distinct new account must be created.
    """
    email = "shared_email_rereg@test.com"

    google_sub = "g_shared_001"
    user = _make_social_user(db, email, provider="google", provider_user_id=google_sub)
    old_id = user.id

    client.delete("/me", headers=_auth(user))

    # Now register with Facebook using the same email address
    fb_id = "fb_shared_001"
    resp = _facebook_login(client, fb_id, email)
    assert resp.status_code == 200, resp.text
    tokens = resp.json()

    new_resp = client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert new_resp.status_code == 200
    assert new_resp.json()["id"] != old_id, "Must not restore the deleted account"


# ── Legacy / lazy-migration ───────────────────────────────────────────────────

def test_legacy_deleted_user_email_not_anonymized_still_rereg(client, db):
    """
    Pre-fix deleted accounts whose email was NOT anonymized (status='deleted' but
    email is still the original) must still allow re-registration.
    The lazy-migration path in _get_or_create_user_by_provider handles this.
    """
    google_sub = "g_legacy_rereg_001"
    email = "legacy_deleted@test.com"

    # Create user and manually simulate a pre-fix soft-delete (no email anonymization)
    user = _make_social_user(db, email, provider="google", provider_user_id=google_sub)
    old_id = user.id

    db.query(UserAuthProvider).filter_by(user_id=user.id).delete()
    user.status = "deleted"
    user.token_version = (user.token_version or 0) + 1
    # Intentionally do NOT anonymize email — simulating old behavior
    db.commit()

    # Re-register with same Google identity
    resp = _google_login(client, google_sub, email)
    assert resp.status_code == 200, resp.text
    tokens = resp.json()

    new_resp = client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert new_resp.status_code == 200
    assert new_resp.json()["id"] != old_id, "Lazy migration must create a fresh account"

    # The old deleted user's email should now be anonymized (lazy migration)
    db.refresh(user)
    assert user.email == f"deleted_{old_id}@deleted.local"


# ── New account isolation ─────────────────────────────────────────────────────

def test_reregister_new_account_has_no_access_to_deleted_account_data(client, db):
    """
    New account created after re-registration must NOT be able to access
    resources that were owned by the deleted account.  Uses GET /me as a proxy:
    the new account should return a different user ID and a fresh profile.
    """
    from app.models.review import Review
    from app.models.organization import Organization

    google_sub = "g_isolation_001"
    email = "isolation_rereg@test.com"

    user = _make_social_user(db, email, provider="google", provider_user_id=google_sub)
    old_id = user.id

    # Attach a review to the old account so there is data to isolate
    org = Organization(name="Test Org", status="active")
    db.add(org)
    db.flush()
    review = Review(
        user_id=old_id,
        organization_id=org.id,
        rating=5,
        comment="Great place",
    )
    db.add(review)
    db.commit()

    client.delete("/me", headers=_auth(user))

    # Re-register
    resp2 = _google_login(client, google_sub, email)
    assert resp2.status_code == 200
    tokens = resp2.json()
    new_token = tokens["access_token"]

    new_me = client.get("/me", headers={"Authorization": f"Bearer {new_token}"})
    assert new_me.status_code == 200
    new_id = new_me.json()["id"]
    assert new_id != old_id

    # The old review is still in the DB (soft-delete preserves history)
    # but it belongs to old_id, not new_id
    db_review = db.query(Review).filter_by(user_id=old_id).first()
    assert db_review is not None, "Review must be preserved (soft-delete, not hard-delete)"
    assert db_review.user_id == old_id
    assert db_review.user_id != new_id
