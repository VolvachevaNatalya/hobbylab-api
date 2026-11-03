"""
Authorization regression tests for organization gallery photo endpoints.

POST /organizations/{org_id}/photos
DELETE /organizations/{org_id}/photos/{photo_id}
GET  /organizations/{org_id}/photos   (public)

Regression: before the fix, _require_org_owner had no role filter, so any
organization member (role='member') could add or delete gallery photos.
Only owners, admins, and system admins must be allowed to mutate photos.
"""
import pytest

from app.core.security import create_access_token, hash_password
from app.models.organization import Organization
from app.models.organization_photo import OrganizationPhoto
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

_PHOTO_URL = "https://static.hobbylab.co.il/gallery/test.jpg"


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


def _make_org(db, name="Test Org"):
    o = Organization(name=name, status="active")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_membership(db, org_id, user_id, role):
    m = OrganizationUser(organization_id=org_id, user_id=user_id, role=role)
    db.add(m)
    db.commit()
    return m


def _make_photo(db, org_id, url=_PHOTO_URL):
    p = OrganizationPhoto(organization_id=org_id, photo_url=url)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


def _photos_url(org_id: int) -> str:
    return f"/organizations/{org_id}/photos"


def _photo_url(org_id: int, photo_id: int) -> str:
    return f"/organizations/{org_id}/photos/{photo_id}"


# ── GET /organizations/{org_id}/photos (public) ───────────────────────────────

def test_get_photos_is_public(client, db):
    org = _make_org(db)
    _make_photo(db, org.id)
    resp = client.get(_photos_url(org.id))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_photos_nonexistent_org_returns_404(client, db):
    assert client.get(_photos_url(999999)).status_code == 404


def test_get_photos_empty_list(client, db):
    org = _make_org(db)
    resp = client.get(_photos_url(org.id))
    assert resp.status_code == 200
    assert resp.json() == []


# ── POST /organizations/{org_id}/photos ───────────────────────────────────────

def test_add_photo_unauthenticated_rejected(client, db):
    org = _make_org(db)
    resp = client.post(_photos_url(org.id), json={"photo_url": _PHOTO_URL})
    assert resp.status_code == 401


def test_add_photo_non_member_rejected(client, db):
    org = _make_org(db)
    user = _make_user(db, "nonmember_add@test.com")
    resp = client.post(
        _photos_url(org.id),
        json={"photo_url": _PHOTO_URL},
        headers=_auth(user.id),
    )
    assert resp.status_code == 403


def test_add_photo_member_rejected(client, db):
    """
    Regression: before the fix, a 'member'-role user could add photos and
    received 201. After the fix it must receive 403.
    """
    org = _make_org(db)
    member = _make_user(db, "member_add@test.com")
    _make_membership(db, org.id, member.id, role="member")
    resp = client.post(
        _photos_url(org.id),
        json={"photo_url": _PHOTO_URL},
        headers=_auth(member.id),
    )
    assert resp.status_code == 403


def test_add_photo_org_admin_allowed(client, db):
    org = _make_org(db)
    admin = _make_user(db, "admin_add@test.com")
    _make_membership(db, org.id, admin.id, role="admin")
    resp = client.post(
        _photos_url(org.id),
        json={"photo_url": _PHOTO_URL},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 201
    assert resp.json()["photo_url"] == _PHOTO_URL


def test_add_photo_org_owner_allowed(client, db):
    org = _make_org(db)
    owner = _make_user(db, "owner_add@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    resp = client.post(
        _photos_url(org.id),
        json={"photo_url": _PHOTO_URL},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 201


def test_add_photo_system_admin_allowed(client, db):
    """System admin must be able to manage photos for any organization."""
    org = _make_org(db)
    sysadmin = _make_user(db, "sysadmin_add@test.com", is_system_admin=True)
    resp = client.post(
        _photos_url(org.id),
        json={"photo_url": _PHOTO_URL},
        headers=_auth(sysadmin.id),
    )
    assert resp.status_code == 201


def test_add_photo_blocked_user_rejected(client, db):
    """Blocked users must be rejected by the auth layer before reaching photo logic."""
    org = _make_org(db)
    blocked = _make_user(db, "blocked_add@test.com", status="blocked")
    _make_membership(db, org.id, blocked.id, role="owner")
    resp = client.post(
        _photos_url(org.id),
        json={"photo_url": _PHOTO_URL},
        headers=_auth(blocked.id),
    )
    assert resp.status_code == 403


def test_add_photo_cross_org_admin_rejected(client, db):
    """An admin of org A must not be able to add photos to org B."""
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    admin_a = _make_user(db, "cross_admin_add@test.com")
    _make_membership(db, org_a.id, admin_a.id, role="admin")
    resp = client.post(
        _photos_url(org_b.id),
        json={"photo_url": _PHOTO_URL},
        headers=_auth(admin_a.id),
    )
    assert resp.status_code == 403


def test_add_photo_nonexistent_org_returns_404(client, db):
    owner = _make_user(db, "owner_404_add@test.com")
    resp = client.post(
        _photos_url(999999),
        json={"photo_url": _PHOTO_URL},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 404


# ── DELETE /organizations/{org_id}/photos/{photo_id} ─────────────────────────

def test_delete_photo_unauthenticated_rejected(client, db):
    org = _make_org(db)
    photo = _make_photo(db, org.id)
    assert client.delete(_photo_url(org.id, photo.id)).status_code == 401


def test_delete_photo_non_member_rejected(client, db):
    org = _make_org(db)
    photo = _make_photo(db, org.id)
    user = _make_user(db, "nonmember_del@test.com")
    assert (
        client.delete(_photo_url(org.id, photo.id), headers=_auth(user.id)).status_code
        == 403
    )


def test_delete_photo_member_rejected(client, db):
    """
    Regression: before the fix, a 'member'-role user could delete photos and
    received 204. After the fix it must receive 403.
    """
    org = _make_org(db)
    photo = _make_photo(db, org.id)
    member = _make_user(db, "member_del@test.com")
    _make_membership(db, org.id, member.id, role="member")
    resp = client.delete(_photo_url(org.id, photo.id), headers=_auth(member.id))
    assert resp.status_code == 403


def test_delete_photo_org_admin_allowed(client, db):
    org = _make_org(db)
    photo = _make_photo(db, org.id)
    admin = _make_user(db, "admin_del@test.com")
    _make_membership(db, org.id, admin.id, role="admin")
    resp = client.delete(_photo_url(org.id, photo.id), headers=_auth(admin.id))
    assert resp.status_code == 204


def test_delete_photo_org_owner_allowed(client, db):
    org = _make_org(db)
    photo = _make_photo(db, org.id)
    owner = _make_user(db, "owner_del@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    resp = client.delete(_photo_url(org.id, photo.id), headers=_auth(owner.id))
    assert resp.status_code == 204


def test_delete_photo_system_admin_allowed(client, db):
    org = _make_org(db)
    photo = _make_photo(db, org.id)
    sysadmin = _make_user(db, "sysadmin_del@test.com", is_system_admin=True)
    resp = client.delete(_photo_url(org.id, photo.id), headers=_auth(sysadmin.id))
    assert resp.status_code == 204


def test_delete_nonexistent_photo_returns_404(client, db):
    org = _make_org(db)
    owner = _make_user(db, "owner_404_del@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    resp = client.delete(_photo_url(org.id, 999999), headers=_auth(owner.id))
    assert resp.status_code == 404


def test_delete_photo_wrong_org_returns_404(client, db):
    """A photo that exists but belongs to a different org must return 404."""
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    photo = _make_photo(db, org_a.id)
    owner_b = _make_user(db, "owner_b_del@test.com")
    _make_membership(db, org_b.id, owner_b.id, role="owner")
    resp = client.delete(_photo_url(org_b.id, photo.id), headers=_auth(owner_b.id))
    assert resp.status_code == 404
