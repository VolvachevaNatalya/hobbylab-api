"""Tests for GET /admin/organizations."""
from app.core.security import create_access_token
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User

_EXPECTED_ORG_FIELDS = {
    "id", "name", "email", "phone", "city", "city_id",
    "status", "verified", "created_at", "owners",
}


def _make_user(db, email, is_system_admin=False):
    u = User(email=email, name="Test", password_hash="x", is_system_admin=is_system_admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, name="Org", status="active"):
    o = Organization(name=name, status=status)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_owner(db, org_id, user_id):
    m = OrganizationUser(organization_id=org_id, user_id=user_id, role="owner")
    db.add(m)
    db.commit()
    return m


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ── Access control ─────────────────────────────────────────────────────────────

def test_admin_orgs_200_for_system_admin(client, db):
    admin = _make_user(db, "ao_admin@x.com", is_system_admin=True)
    resp = client.get("/admin/organizations", headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_orgs_403_for_normal_user(client, db):
    user = _make_user(db, "ao_user@x.com")
    resp = client.get("/admin/organizations", headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_orgs_401_for_unauthenticated(client, db):
    resp = client.get("/admin/organizations")
    assert resp.status_code == 401


# ── Response shape ─────────────────────────────────────────────────────────────

def test_admin_orgs_response_envelope(client, db):
    admin = _make_user(db, "ao_env@x.com", is_system_admin=True)
    resp = client.get("/admin/organizations", headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"items", "total", "limit", "offset"}


def test_admin_orgs_item_fields_exact(client, db):
    admin = _make_user(db, "ao_fields@x.com", is_system_admin=True)
    _make_org(db, name="FieldsOrg")
    resp = client.get("/admin/organizations", headers=_auth(admin.id))
    items = resp.json()["items"]
    assert len(items) >= 1
    item = next(i for i in items if i["name"] == "FieldsOrg")
    assert set(item.keys()) == _EXPECTED_ORG_FIELDS


def test_admin_orgs_no_sensitive_fields(client, db):
    admin = _make_user(db, "ao_safe@x.com", is_system_admin=True)
    _make_org(db, name="SafeOrg")
    resp = client.get("/admin/organizations", headers=_auth(admin.id))
    for item in resp.json()["items"]:
        assert "latitude" not in item
        assert "longitude" not in item
        assert "description" not in item
        assert "instagram_url" not in item
        assert "facebook_url" not in item
        assert "banner_url" not in item
        assert "logo_url" not in item


# ── Owner information ──────────────────────────────────────────────────────────

def test_admin_orgs_owners_included(client, db):
    admin = _make_user(db, "ao_own_adm@x.com", is_system_admin=True)
    owner = _make_user(db, "ao_owner@x.com")
    org = _make_org(db, name="OwnedOrg")
    _make_owner(db, org.id, owner.id)

    resp = client.get("/admin/organizations", headers=_auth(admin.id))
    items = resp.json()["items"]
    item = next(i for i in items if i["name"] == "OwnedOrg")
    assert len(item["owners"]) == 1
    o = item["owners"][0]
    assert o["id"] == owner.id
    assert o["email"] == "ao_owner@x.com"
    assert "password_hash" not in o
    assert set(o.keys()) == {"id", "name", "email"}


def test_admin_orgs_no_owner_returns_empty_list(client, db):
    admin = _make_user(db, "ao_noown_adm@x.com", is_system_admin=True)
    _make_org(db, name="OwnerlessOrg")

    resp = client.get("/admin/organizations", headers=_auth(admin.id))
    items = resp.json()["items"]
    item = next(i for i in items if i["name"] == "OwnerlessOrg")
    assert item["owners"] == []


# ── Pagination ─────────────────────────────────────────────────────────────────

def test_admin_orgs_default_pagination(client, db):
    admin = _make_user(db, "ao_pg_adm@x.com", is_system_admin=True)
    resp = client.get("/admin/organizations", headers=_auth(admin.id))
    data = resp.json()
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_admin_orgs_limit_offset(client, db):
    admin = _make_user(db, "ao_lo_adm@x.com", is_system_admin=True)
    for i in range(6):
        _make_org(db, name=f"LO_Org_{i}")

    total = client.get("/admin/organizations", params={"limit": 100},
                       headers=_auth(admin.id)).json()["total"]
    assert total >= 6

    p1 = client.get("/admin/organizations", params={"limit": 3, "offset": 0},
                    headers=_auth(admin.id)).json()
    p2 = client.get("/admin/organizations", params={"limit": 3, "offset": 3},
                    headers=_auth(admin.id)).json()

    ids_p1 = {i["id"] for i in p1["items"]}
    ids_p2 = {i["id"] for i in p2["items"]}
    assert len(ids_p1) == 3
    assert len(ids_p2) == 3
    assert ids_p1.isdisjoint(ids_p2)
    assert p1["total"] == p2["total"] == total
    assert p1["limit"] == p2["limit"] == 3
    assert p2["offset"] == 3


def test_admin_orgs_limit_above_100_returns_422(client, db):
    admin = _make_user(db, "ao_cap_adm@x.com", is_system_admin=True)
    resp = client.get("/admin/organizations", params={"limit": 101},
                      headers=_auth(admin.id))
    assert resp.status_code == 422


# ── Ordering ──────────────────────────────────────────────────────────────────

def test_admin_orgs_newest_first(client, db):
    admin = _make_user(db, "ao_ord_adm@x.com", is_system_admin=True)
    o1 = _make_org(db, name="Ord_A")
    o2 = _make_org(db, name="Ord_B")
    o3 = _make_org(db, name="Ord_C")

    resp = client.get("/admin/organizations", headers=_auth(admin.id))
    ids = [i["id"] for i in resp.json()["items"]]
    pos = {oid: ids.index(oid) for oid in [o1.id, o2.id, o3.id]}
    # o3 created last → appears first
    assert pos[o3.id] < pos[o2.id] < pos[o1.id]
