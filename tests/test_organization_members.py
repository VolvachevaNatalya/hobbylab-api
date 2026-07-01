from app.core.security import create_access_token
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="user@test.com", name="Test User"):
    user = User(email=email, name=name, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_org(db, name="Test Org"):
    org = Organization(name=name, status="active", verified=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _make_membership(db, org_id, user_id, role="owner"):
    row = OrganizationUser(organization_id=org_id, user_id=user_id, role=role)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ── LIST MEMBERS ──────────────────────────────────────────────────────────────

def test_owner_can_list_members(client, db):
    owner = _make_user(db, email="owner@test.com", name="Owner")
    admin = _make_user(db, email="admin@test.com", name="Admin")
    member = _make_user(db, email="member@test.com", name="Member")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, admin.id, role="admin")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.get(f"/organizations/{org.id}/members", headers=_auth(owner.id))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    roles = {d["role"] for d in data}
    assert roles == {"owner", "admin", "member"}


def test_admin_can_list_members(client, db):
    owner = _make_user(db, email="owner@test.com")
    admin = _make_user(db, email="admin@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, admin.id, role="admin")

    resp = client.get(f"/organizations/{org.id}/members", headers=_auth(admin.id))
    assert resp.status_code == 200


def test_member_cannot_list_members(client, db):
    owner = _make_user(db, email="owner@test.com")
    member = _make_user(db, email="member@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.get(f"/organizations/{org.id}/members", headers=_auth(member.id))
    assert resp.status_code == 403


def test_list_members_unauthenticated(client, db):
    org = _make_org(db)
    resp = client.get(f"/organizations/{org.id}/members")
    assert resp.status_code == 401


def test_list_members_response_fields(client, db):
    owner = _make_user(db, email="owner@test.com", name="Alice Owner")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")

    resp = client.get(f"/organizations/{org.id}/members", headers=_auth(owner.id))
    assert resp.status_code == 200
    entry = resp.json()[0]
    assert entry["user_id"] == owner.id
    assert entry["name"] == "Alice Owner"
    assert entry["email"] == "owner@test.com"
    assert entry["role"] == "owner"
    assert "joined_at" in entry


# ── CHANGE ROLE ───────────────────────────────────────────────────────────────

def test_owner_can_promote_member_to_admin(client, db):
    owner = _make_user(db, email="owner@test.com")
    member = _make_user(db, email="member@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.patch(
        f"/organizations/{org.id}/members/{member.id}/role",
        json={"role": "admin"},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"

    db.expire_all()
    updated = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org.id,
        OrganizationUser.user_id == member.id,
    ).first()
    assert updated.role == "admin"


def test_owner_can_demote_admin_to_member(client, db):
    owner = _make_user(db, email="owner@test.com")
    admin = _make_user(db, email="admin@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, admin.id, role="admin")

    resp = client.patch(
        f"/organizations/{org.id}/members/{admin.id}/role",
        json={"role": "member"},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "member"


def test_admin_cannot_change_roles(client, db):
    owner = _make_user(db, email="owner@test.com")
    admin = _make_user(db, email="admin@test.com")
    member = _make_user(db, email="member@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, admin.id, role="admin")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.patch(
        f"/organizations/{org.id}/members/{member.id}/role",
        json={"role": "admin"},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 403


def test_member_cannot_change_roles(client, db):
    owner = _make_user(db, email="owner@test.com")
    member = _make_user(db, email="member@test.com")
    other = _make_user(db, email="other@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")
    _make_membership(db, org.id, other.id, role="member")

    resp = client.patch(
        f"/organizations/{org.id}/members/{other.id}/role",
        json={"role": "admin"},
        headers=_auth(member.id),
    )
    assert resp.status_code == 403


def test_cannot_change_owner_role(client, db):
    owner = _make_user(db, email="owner@test.com")
    co_owner = _make_user(db, email="coowner@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, co_owner.id, role="owner")

    resp = client.patch(
        f"/organizations/{org.id}/members/{co_owner.id}/role",
        json={"role": "member"},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 403


def test_cannot_set_role_to_owner(client, db):
    owner = _make_user(db, email="owner@test.com")
    member = _make_user(db, email="member@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.patch(
        f"/organizations/{org.id}/members/{member.id}/role",
        json={"role": "owner"},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 422


def test_change_role_unauthenticated(client, db):
    owner = _make_user(db, email="owner@test.com")
    member = _make_user(db, email="member@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.patch(
        f"/organizations/{org.id}/members/{member.id}/role",
        json={"role": "admin"},
    )
    assert resp.status_code == 401


def test_change_role_target_not_found(client, db):
    owner = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")

    resp = client.patch(
        f"/organizations/{org.id}/members/99999/role",
        json={"role": "admin"},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 404


# ── REMOVE MEMBER ─────────────────────────────────────────────────────────────

def test_owner_can_remove_member(client, db):
    owner = _make_user(db, email="owner@test.com")
    member = _make_user(db, email="member@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    row = _make_membership(db, org.id, member.id, role="member")

    resp = client.delete(
        f"/organizations/{org.id}/members/{member.id}",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    gone = db.query(OrganizationUser).filter(OrganizationUser.id == row.id).first()
    assert gone is None


def test_admin_can_remove_member(client, db):
    owner = _make_user(db, email="owner@test.com")
    admin = _make_user(db, email="admin@test.com")
    member = _make_user(db, email="member@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, admin.id, role="admin")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.delete(
        f"/organizations/{org.id}/members/{member.id}",
        headers=_auth(admin.id),
    )
    assert resp.status_code == 200


def test_cannot_remove_owner(client, db):
    owner = _make_user(db, email="owner@test.com")
    co_owner = _make_user(db, email="coowner@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, co_owner.id, role="owner")

    resp = client.delete(
        f"/organizations/{org.id}/members/{co_owner.id}",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 403


def test_admin_cannot_remove_owner(client, db):
    owner = _make_user(db, email="owner@test.com")
    admin = _make_user(db, email="admin@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, admin.id, role="admin")

    resp = client.delete(
        f"/organizations/{org.id}/members/{owner.id}",
        headers=_auth(admin.id),
    )
    assert resp.status_code == 403


def test_owner_cannot_remove_self(client, db):
    owner = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")

    resp = client.delete(
        f"/organizations/{org.id}/members/{owner.id}",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 403


def test_admin_cannot_remove_self(client, db):
    owner = _make_user(db, email="owner@test.com")
    admin = _make_user(db, email="admin@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, admin.id, role="admin")

    resp = client.delete(
        f"/organizations/{org.id}/members/{admin.id}",
        headers=_auth(admin.id),
    )
    assert resp.status_code == 403


def test_member_cannot_remove_anyone(client, db):
    owner = _make_user(db, email="owner@test.com")
    member = _make_user(db, email="member@test.com")
    other = _make_user(db, email="other@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")
    _make_membership(db, org.id, other.id, role="member")

    resp = client.delete(
        f"/organizations/{org.id}/members/{other.id}",
        headers=_auth(member.id),
    )
    assert resp.status_code == 403


def test_remove_unauthenticated(client, db):
    owner = _make_user(db, email="owner@test.com")
    member = _make_user(db, email="member@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.delete(f"/organizations/{org.id}/members/{member.id}")
    assert resp.status_code == 401


def test_remove_target_not_in_org(client, db):
    owner = _make_user(db, email="owner@test.com")
    stranger = _make_user(db, email="stranger@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")

    resp = client.delete(
        f"/organizations/{org.id}/members/{stranger.id}",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 404
