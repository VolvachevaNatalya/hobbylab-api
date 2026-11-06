"""
Regression tests for two P2 security findings in the organization endpoints.

P2-1: Org status self-unblock
  An organization owner could call PUT /organizations/{id} with {"status": "active"}
  to restore a blocked org to public visibility, bypassing admin moderation.

P2-2: _get_optional_user bypasses token_version
  After a password change, the optional-auth dependency used by
  GET /organizations/{id} did not verify the "tv" (token_version) claim.
  A stale token could still grant org-owner privileges on that endpoint.
"""
import pytest

from app.core.security import create_access_token, hash_password
from app.models.category import Category
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User

_ORG_URL = "/organizations/{id}"
_ORG_UPDATE_URL = "/organizations/{id}"


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_user(db, email, password="pw", is_admin=False):
    u = User(
        email=email,
        name="Test",
        password_hash=hash_password(password),
        status="active",
        is_system_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_category(db, name="Cat"):
    c = Category(name=name, name_en=name, name_ru=name, name_he=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_org(db, name="Org", status="pending", verified=False):
    o = Organization(name=name, status=status, verified=verified)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_owner(db, org_id, user_id):
    m = OrganizationUser(organization_id=org_id, user_id=user_id, role="owner")
    db.add(m)
    db.commit()


def _auth(user_id: int, tv: int = 0) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id, 'tv': tv})}"}


# ═══════════════════════════════════════════════════════════════════════════════
# P2-1: Organization status self-unblock
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrgStatusSelfUnblock:
    """
    Regression: PUT /organizations/{id} accepted a 'status' field from the
    org owner, allowing a blocked org to restore itself to active+visible.
    """

    def test_owner_cannot_set_status_active_on_blocked_org(self, client, db):
        """
        Regression: a blocked org's owner must not be able to self-unblock.
        Before the fix: status changed to "active", org reappeared in listings.
        After the fix:  the update must be rejected or the status must remain.
        """
        owner = _make_user(db, "unblock_owner@test.com")
        org = _make_org(db, name="Blocked Org", status="blocked", verified=True)
        _make_owner(db, org.id, owner.id)

        resp = client.put(
            f"/organizations/{org.id}",
            json={"status": "active"},
            headers=_auth(owner.id),
        )

        # Must be rejected (422) or the status must remain "blocked".
        db.refresh(org)
        assert resp.status_code == 422 or org.status == "blocked", (
            f"Owner self-unblocked org: HTTP {resp.status_code}, "
            f"org.status={org.status!r}"
        )

    def test_owner_cannot_set_status_active_on_pending_org(self, client, db):
        """
        Regression: a pending org's owner must not be able to self-activate.
        Only a system admin may move an org from pending to active.
        """
        owner = _make_user(db, "pending_owner@test.com")
        org = _make_org(db, name="Pending Org", status="pending", verified=False)
        _make_owner(db, org.id, owner.id)

        resp = client.put(
            f"/organizations/{org.id}",
            json={"status": "active"},
            headers=_auth(owner.id),
        )

        db.refresh(org)
        assert resp.status_code == 422 or org.status == "pending", (
            f"Owner self-activated pending org: HTTP {resp.status_code}, "
            f"org.status={org.status!r}"
        )

    def test_owner_cannot_set_status_to_any_value(self, client, db):
        """Any status value submitted by an org owner must be ignored or rejected."""
        owner = _make_user(db, "any_status_owner@test.com")
        org = _make_org(db, name="Any Status Org", status="pending", verified=False)
        _make_owner(db, org.id, owner.id)

        for bad_status in ("active", "blocked", "pending"):
            resp = client.put(
                f"/organizations/{org.id}",
                json={"status": bad_status},
                headers=_auth(owner.id),
            )
            db.refresh(org)
            assert resp.status_code == 422 or org.status == "pending", (
                f"Owner changed status to {bad_status!r}: "
                f"HTTP {resp.status_code}, org.status={org.status!r}"
            )

    def test_owner_can_still_update_profile_fields(self, client, db):
        """
        Positive-case regression: removing 'status' from OrganizationUpdate
        must not break legitimate profile edits.
        """
        cat = _make_category(db, "Sport")
        owner = _make_user(db, "profile_owner@test.com")
        org = _make_org(db, name="Old Name", status="active", verified=True)
        _make_owner(db, org.id, owner.id)

        resp = client.put(
            f"/organizations/{org.id}",
            json={
                "name": "New Name",
                "description": "Updated description",
                "phone": "050-1234567",
                "category_ids": [cat.id],
            },
            headers=_auth(owner.id),
        )

        assert resp.status_code == 200, f"Profile update rejected: {resp.json()}"
        data = resp.json()
        assert data["name"] == "New Name"
        assert data["description"] == "Updated description"
        assert data["phone"] == "050-1234567"

    def test_sysadmin_can_still_change_org_status_via_admin_endpoint(self, client, db):
        """
        Removing 'status' from OrganizationUpdate must not affect the admin
        endpoint (PATCH /admin/organizations/{id}), which uses AdminOrganizationUpdate.
        """
        sysadmin = _make_user(db, "sysadmin_status@test.com", is_admin=True)
        org = _make_org(db, name="Admin Org", status="pending", verified=False)

        resp = client.patch(
            f"/admin/organizations/{org.id}",
            json={"status": "active", "verified": True},
            headers=_auth(sysadmin.id),
        )

        assert resp.status_code == 200, f"Admin org status change failed: {resp.json()}"
        data = resp.json()
        assert data["status"] == "active"
        assert data["verified"] is True

    def test_blocked_org_stays_hidden_after_attempted_self_unblock(self, client, db):
        """
        End-to-end: even if an owner attempts the self-unblock, the org must
        not reappear in public listings afterwards.
        """
        owner = _make_user(db, "e2e_unblock@test.com")
        org = _make_org(db, name="E2E Blocked", status="blocked", verified=True)
        _make_owner(db, org.id, owner.id)

        # Attempt self-unblock
        client.put(
            f"/organizations/{org.id}",
            json={"status": "active"},
            headers=_auth(owner.id),
        )

        # Public listing must not include the org.
        anon_resp = client.get(f"/organizations/{org.id}")
        assert anon_resp.status_code == 404, (
            f"Blocked org visible after self-unblock attempt: {anon_resp.json()}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# P2-2: _get_optional_user must verify token_version
# ═══════════════════════════════════════════════════════════════════════════════

class TestOptionalUserTokenVersion:
    """
    Regression: _get_optional_user in app/api/organizations.py decoded the JWT
    and looked up the user but did not verify the "tv" (token_version) claim.

    After a password change increments token_version to 1, a stale token
    (tv=0) was still accepted as the authenticated user, granting org-owner
    privileges on GET /organizations/{id}.

    After the fix: stale tokens must be treated as anonymous.  An anonymous
    caller cannot see a pending/blocked org, so they must receive 404.
    """

    def test_stale_token_cannot_see_own_pending_org(self, client, db):
        """
        Regression: stale token (tv=0) must not grant owner-privilege access
        to a pending org after password change (token_version=1).
        Before fix: returned 200.  After fix: must return 404.
        """
        owner = _make_user(db, "tv_opt_pending@test.com")
        org = _make_org(db, name="TV Pending", status="pending", verified=False)
        _make_owner(db, org.id, owner.id)

        # Simulate post-password-change state: token_version=1, stale token tv=0
        owner.token_version = 1
        db.commit()

        stale_headers = _auth(owner.id, tv=0)
        resp = client.get(f"/organizations/{org.id}", headers=stale_headers)

        assert resp.status_code == 404, (
            f"Stale token granted access to pending org: "
            f"HTTP {resp.status_code} (expected 404)"
        )

    def test_stale_token_cannot_see_own_blocked_org(self, client, db):
        """
        A stale token must not reveal a blocked (but verified) org to its owner.
        Before fix: stale token returned 200.  After fix: must return 404.
        """
        owner = _make_user(db, "tv_opt_blocked@test.com")
        org = _make_org(db, name="TV Blocked", status="blocked", verified=True)
        _make_owner(db, org.id, owner.id)

        owner.token_version = 1
        db.commit()

        stale_headers = _auth(owner.id, tv=0)
        resp = client.get(f"/organizations/{org.id}", headers=stale_headers)

        assert resp.status_code == 404, (
            f"Stale token granted access to blocked org: "
            f"HTTP {resp.status_code} (expected 404)"
        )

    def test_fresh_token_can_see_own_pending_org(self, client, db):
        """
        Positive case: a valid token with the current tv must still grant
        owner-privilege access to a pending org.
        """
        owner = _make_user(db, "tv_opt_fresh@test.com")
        org = _make_org(db, name="TV Fresh", status="pending", verified=False)
        _make_owner(db, org.id, owner.id)

        owner.token_version = 1
        db.commit()

        fresh_headers = _auth(owner.id, tv=1)
        resp = client.get(f"/organizations/{org.id}", headers=fresh_headers)

        assert resp.status_code == 200, (
            f"Fresh token rejected from own pending org: "
            f"HTTP {resp.status_code}"
        )

    def test_anonymous_can_still_see_active_verified_org(self, client, db):
        """
        Positive case: public (unauthenticated) access to active + verified
        orgs must remain unaffected by the tv check.
        """
        org = _make_org(db, name="Public Org", status="active", verified=True)
        resp = client.get(f"/organizations/{org.id}")
        assert resp.status_code == 200

    def test_legacy_token_no_tv_claim_still_works_for_new_user(self, client, db):
        """
        Backward-compat: tokens without a "tv" claim (issued before this fix)
        must still work for users whose token_version is 0.
        """
        owner = _make_user(db, "tv_opt_legacy@test.com")
        org = _make_org(db, name="Legacy Org", status="pending", verified=False)
        _make_owner(db, org.id, owner.id)

        # token_version remains 0 (never changed password)
        legacy_token = create_access_token({"user_id": owner.id})  # no tv
        resp = client.get(
            f"/organizations/{org.id}",
            headers={"Authorization": f"Bearer {legacy_token}"},
        )

        assert resp.status_code == 200, (
            f"Legacy token (no tv) rejected for user with token_version=0: "
            f"HTTP {resp.status_code}"
        )
