"""
Regression tests for P2-5: GET /organizations/{id} returning inactive or unverified orgs.

Before the fix the single-org endpoint had no status/verified filter, so any
anonymous user could retrieve orgs that are pending, blocked, or unverified.
The list endpoint already filtered these out; the single endpoint must too.

Privileged actors (system admin, org owner/admin) retain access to their own
non-active orgs so they can manage them before activation.
"""
import pytest

from app.core.security import create_access_token, hash_password
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False, status="active"):
    u = User(
        email=email,
        name="Test",
        password_hash=hash_password("pw"),
        is_system_admin=is_system_admin,
        status=status,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, name="Test Org", status="active", verified=True):
    o = Organization(name=name, status=status, verified=verified)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_membership(db, org_id, user_id, role):
    m = OrganizationUser(organization_id=org_id, user_id=user_id, role=role)
    db.add(m)
    db.commit()
    return m


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


def _org_url(org_id: int) -> str:
    return f"/organizations/{org_id}"


# ── Public access to active, verified orgs (must keep working) ───────────────

def test_get_active_verified_org_anonymous_returns_200(client, db):
    org = _make_org(db, status="active", verified=True)
    resp = client.get(_org_url(org.id))
    assert resp.status_code == 200
    assert resp.json()["id"] == org.id


def test_get_nonexistent_org_returns_404(client, db):
    assert client.get(_org_url(999999)).status_code == 404


# ── Regression: public access to non-active orgs must be blocked ─────────────

def test_get_pending_org_anonymous_returns_404(client, db):
    """
    Before the fix: GET returned 200 for pending orgs.
    After the fix:  must return 404.
    """
    org = _make_org(db, status="pending", verified=False)
    resp = client.get(_org_url(org.id))
    assert resp.status_code == 404


def test_get_blocked_org_anonymous_returns_404(client, db):
    """
    Before the fix: GET returned 200 for blocked orgs.
    After the fix:  must return 404.
    """
    org = _make_org(db, status="blocked", verified=True)
    resp = client.get(_org_url(org.id))
    assert resp.status_code == 404


def test_get_active_unverified_org_anonymous_returns_404(client, db):
    """
    Before the fix: GET returned 200 for active but unverified orgs.
    After the fix:  must return 404.
    """
    org = _make_org(db, status="active", verified=False)
    resp = client.get(_org_url(org.id))
    assert resp.status_code == 404


def test_get_pending_org_unrelated_user_returns_404(client, db):
    """An authenticated user with no membership must not see a pending org."""
    org = _make_org(db, status="pending", verified=False)
    user = _make_user(db, "unrelated@test.com")
    resp = client.get(_org_url(org.id), headers=_auth(user.id))
    assert resp.status_code == 404


def test_get_pending_org_member_returns_404(client, db):
    """A regular member (role='member') must not see a pending org."""
    org = _make_org(db, status="pending", verified=False)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")
    resp = client.get(_org_url(org.id), headers=_auth(member.id))
    assert resp.status_code == 404


# ── Privileged access: owners and admins can see their own non-active orgs ────

def test_get_pending_org_owner_returns_200(client, db):
    """Organization owner must be able to see their own pending org."""
    org = _make_org(db, status="pending", verified=False)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    resp = client.get(_org_url(org.id), headers=_auth(owner.id))
    assert resp.status_code == 200
    assert resp.json()["id"] == org.id


def test_get_pending_org_org_admin_returns_200(client, db):
    """Organization admin must be able to see a pending org they manage."""
    org = _make_org(db, status="pending", verified=False)
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, admin.id, role="admin")
    resp = client.get(_org_url(org.id), headers=_auth(admin.id))
    assert resp.status_code == 200


def test_get_pending_org_sysadmin_returns_200(client, db):
    """System admin must be able to see any org regardless of status."""
    org = _make_org(db, status="pending", verified=False)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    resp = client.get(_org_url(org.id), headers=_auth(sysadmin.id))
    assert resp.status_code == 200


def test_get_blocked_org_sysadmin_returns_200(client, db):
    org = _make_org(db, status="blocked", verified=True)
    sysadmin = _make_user(db, "sysadmin2@test.com", is_system_admin=True)
    resp = client.get(_org_url(org.id), headers=_auth(sysadmin.id))
    assert resp.status_code == 200


def test_get_pending_org_admin_of_different_org_returns_404(client, db):
    """An admin of org A must not see pending org B via this privilege."""
    org_a = _make_org(db, name="Org A", status="active", verified=True)
    org_b = _make_org(db, name="Org B", status="pending", verified=False)
    admin_a = _make_user(db, "admin_a@test.com")
    _make_membership(db, org_a.id, admin_a.id, role="admin")
    resp = client.get(_org_url(org_b.id), headers=_auth(admin_a.id))
    assert resp.status_code == 404
