from datetime import datetime, timedelta

from app.core.security import create_access_token
from app.models.organization import Organization
from app.models.organization_invite_code import OrganizationInviteCode
from app.models.organization_join_request import OrganizationJoinRequest
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
    return row


def _make_invite_code(
    db, org_id, user_id,
    code="TESTCODE",
    default_role="member",
    requires_approval=True,
    is_active=True,
    expires_at=None,
):
    invite = OrganizationInviteCode(
        organization_id=org_id,
        code=code,
        default_role=default_role,
        requires_approval=requires_approval,
        is_active=is_active,
        expires_at=expires_at,
        created_by_user_id=user_id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ── CREATE INVITE CODE ────────────────────────────────────────────────────────

def test_create_invite_code_as_owner(client, db):
    owner = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")

    resp = client.post(
        f"/organizations/{org.id}/invite-codes",
        json={"default_role": "member", "requires_approval": True},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["default_role"] == "member"
    assert data["is_active"] is True
    assert data["requires_approval"] is True
    assert len(data["code"]) == 8


def test_create_invite_code_as_admin(client, db):
    admin = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, admin.id, role="admin")

    resp = client.post(
        f"/organizations/{org.id}/invite-codes",
        json={"default_role": "admin"},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 201
    assert resp.json()["default_role"] == "admin"


def test_create_invite_code_as_member_forbidden(client, db):
    member = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, member.id, role="member")

    resp = client.post(
        f"/organizations/{org.id}/invite-codes",
        json={"default_role": "member"},
        headers=_auth(member.id),
    )
    assert resp.status_code == 403


def test_create_invite_code_unauthenticated(client, db):
    org = _make_org(db)
    resp = client.post(f"/organizations/{org.id}/invite-codes", json={"default_role": "member"})
    assert resp.status_code == 401


def test_create_invite_code_owner_role_rejected(client, db):
    owner = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")

    resp = client.post(
        f"/organizations/{org.id}/invite-codes",
        json={"default_role": "owner"},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 422


# ── LIST INVITE CODES ─────────────────────────────────────────────────────────

def test_list_invite_codes(client, db):
    owner = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_invite_code(db, org.id, owner.id, code="CODE0001")
    _make_invite_code(db, org.id, owner.id, code="CODE0002")

    resp = client.get(f"/organizations/{org.id}/invite-codes", headers=_auth(owner.id))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_invite_codes_non_member_forbidden(client, db):
    user = _make_user(db)
    org = _make_org(db)

    resp = client.get(f"/organizations/{org.id}/invite-codes", headers=_auth(user.id))
    assert resp.status_code == 403


# ── DEACTIVATE INVITE CODE ────────────────────────────────────────────────────

def test_deactivate_invite_code(client, db):
    owner = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id)

    resp = client.patch(
        f"/organizations/{org.id}/invite-codes/{invite.id}/deactivate",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_deactivate_code_from_different_org_not_found(client, db):
    owner = _make_user(db)
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    _make_membership(db, org_a.id, owner.id, role="owner")
    _make_membership(db, org_b.id, owner.id, role="owner")
    invite_b = _make_invite_code(db, org_b.id, owner.id, code="CODEB001")

    resp = client.patch(
        f"/organizations/{org_a.id}/invite-codes/{invite_b.id}/deactivate",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 404


# ── SUBMIT JOIN REQUEST ───────────────────────────────────────────────────────

def test_submit_join_request_requires_approval(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id, requires_approval=True)

    resp = client.post(
        f"/organizations/{org.id}/join-requests",
        json={"code": invite.code},
        headers=_auth(user.id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["requires_approval"] is True
    assert data["join_request_id"] is not None
    assert data["role"] is None


def test_submit_join_request_auto_approve(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id, requires_approval=False)

    resp = client.post(
        f"/organizations/{org.id}/join-requests",
        json={"code": invite.code},
        headers=_auth(user.id),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["requires_approval"] is False
    assert data["role"] == "member"
    assert data["join_request_id"] is None

    membership = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org.id,
        OrganizationUser.user_id == user.id,
    ).first()
    assert membership is not None
    assert membership.role == "member"


def test_auto_approve_cleans_up_pending_request(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")

    code_manual = _make_invite_code(db, org.id, owner.id, code="MANUAL01", requires_approval=True)
    resp1 = client.post(
        f"/organizations/{org.id}/join-requests",
        json={"code": code_manual.code},
        headers=_auth(user.id),
    )
    assert resp1.status_code == 201

    code_auto = _make_invite_code(db, org.id, owner.id, code="AUTO0001", requires_approval=False)
    resp2 = client.post(
        f"/organizations/{org.id}/join-requests",
        json={"code": code_auto.code},
        headers=_auth(user.id),
    )
    assert resp2.status_code == 201
    assert resp2.json()["requires_approval"] is False

    db.expire_all()
    remaining = db.query(OrganizationJoinRequest).filter(
        OrganizationJoinRequest.organization_id == org.id,
        OrganizationJoinRequest.user_id == user.id,
    ).first()
    assert remaining is None


def test_submit_join_request_inactive_code(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id, is_active=False)

    resp = client.post(
        f"/organizations/{org.id}/join-requests",
        json={"code": invite.code},
        headers=_auth(user.id),
    )
    assert resp.status_code == 400


def test_submit_join_request_expired_code(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    past = datetime.utcnow() - timedelta(days=1)
    invite = _make_invite_code(db, org.id, owner.id, expires_at=past)

    resp = client.post(
        f"/organizations/{org.id}/join-requests",
        json={"code": invite.code},
        headers=_auth(user.id),
    )
    assert resp.status_code == 400


def test_submit_join_request_unknown_code(client, db):
    user = _make_user(db)
    org = _make_org(db)

    resp = client.post(
        f"/organizations/{org.id}/join-requests",
        json={"code": "NOTEXIST"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 404


def test_submit_join_request_code_from_different_org(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    _make_membership(db, org_a.id, owner.id, role="owner")
    _make_membership(db, org_b.id, owner.id, role="owner")
    invite_b = _make_invite_code(db, org_b.id, owner.id, code="CODEB001")

    resp = client.post(
        f"/organizations/{org_a.id}/join-requests",
        json={"code": invite_b.code},
        headers=_auth(user.id),
    )
    assert resp.status_code == 404


def test_submit_join_request_already_member(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, user.id, role="member")
    invite = _make_invite_code(db, org.id, owner.id)

    resp = client.post(
        f"/organizations/{org.id}/join-requests",
        json={"code": invite.code},
        headers=_auth(user.id),
    )
    assert resp.status_code == 409


def test_submit_join_request_duplicate_pending(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id)

    resp1 = client.post(
        f"/organizations/{org.id}/join-requests",
        json={"code": invite.code},
        headers=_auth(user.id),
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        f"/organizations/{org.id}/join-requests",
        json={"code": invite.code},
        headers=_auth(user.id),
    )
    assert resp2.status_code == 409


def test_submit_join_request_unauthenticated(client, db):
    org = _make_org(db)
    resp = client.post(f"/organizations/{org.id}/join-requests", json={"code": "ANYCODE"})
    assert resp.status_code == 401


# ── LIST JOIN REQUESTS ────────────────────────────────────────────────────────

def test_list_join_requests(client, db):
    owner = _make_user(db, email="owner@test.com")
    user1 = _make_user(db, email="user1@test.com", name="User One")
    user2 = _make_user(db, email="user2@test.com", name="User Two")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id)

    client.post(f"/organizations/{org.id}/join-requests",
                json={"code": invite.code}, headers=_auth(user1.id))
    client.post(f"/organizations/{org.id}/join-requests",
                json={"code": invite.code}, headers=_auth(user2.id))

    resp = client.get(f"/organizations/{org.id}/join-requests", headers=_auth(owner.id))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    emails = {r["user_email"] for r in data}
    assert emails == {"user1@test.com", "user2@test.com"}


def test_list_join_requests_includes_user_name(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com", name="Alice")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id)
    client.post(f"/organizations/{org.id}/join-requests",
                json={"code": invite.code}, headers=_auth(user.id))

    resp = client.get(f"/organizations/{org.id}/join-requests", headers=_auth(owner.id))
    assert resp.json()[0]["user_name"] == "Alice"


def test_list_join_requests_member_forbidden(client, db):
    member = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, member.id, role="member")

    resp = client.get(f"/organizations/{org.id}/join-requests", headers=_auth(member.id))
    assert resp.status_code == 403


# ── APPROVE JOIN REQUEST ──────────────────────────────────────────────────────

def test_approve_join_request(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id, default_role="member")

    sub = client.post(f"/organizations/{org.id}/join-requests",
                      json={"code": invite.code}, headers=_auth(user.id))
    request_id = sub.json()["join_request_id"]

    resp = client.post(
        f"/organizations/{org.id}/join-requests/{request_id}/approve",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200

    membership = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org.id,
        OrganizationUser.user_id == user.id,
    ).first()
    assert membership is not None
    assert membership.role == "member"

    db.expire_all()
    gone = db.query(OrganizationJoinRequest).filter(
        OrganizationJoinRequest.id == request_id,
    ).first()
    assert gone is None


def test_approve_assigns_role_from_invite_code(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id, default_role="admin")

    sub = client.post(f"/organizations/{org.id}/join-requests",
                      json={"code": invite.code}, headers=_auth(user.id))
    request_id = sub.json()["join_request_id"]

    client.post(f"/organizations/{org.id}/join-requests/{request_id}/approve",
                headers=_auth(owner.id))

    membership = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org.id,
        OrganizationUser.user_id == user.id,
    ).first()
    assert membership.role == "admin"


def test_approve_join_request_as_member_forbidden(client, db):
    owner = _make_user(db, email="owner@test.com")
    member = _make_user(db, email="member@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")
    invite = _make_invite_code(db, org.id, owner.id)

    sub = client.post(f"/organizations/{org.id}/join-requests",
                      json={"code": invite.code}, headers=_auth(user.id))
    request_id = sub.json()["join_request_id"]

    resp = client.post(
        f"/organizations/{org.id}/join-requests/{request_id}/approve",
        headers=_auth(member.id),
    )
    assert resp.status_code == 403


def test_approve_nonexistent_request(client, db):
    owner = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")

    resp = client.post(
        f"/organizations/{org.id}/join-requests/99999/approve",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 404


def test_approve_request_from_different_org_not_found(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    _make_membership(db, org_a.id, owner.id, role="owner")
    _make_membership(db, org_b.id, owner.id, role="owner")
    invite_b = _make_invite_code(db, org_b.id, owner.id, code="CODEB001")

    sub = client.post(f"/organizations/{org_b.id}/join-requests",
                      json={"code": invite_b.code}, headers=_auth(user.id))
    request_id = sub.json()["join_request_id"]

    resp = client.post(
        f"/organizations/{org_a.id}/join-requests/{request_id}/approve",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 404


# ── REJECT JOIN REQUEST ───────────────────────────────────────────────────────

def test_reject_join_request(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id)

    sub = client.post(f"/organizations/{org.id}/join-requests",
                      json={"code": invite.code}, headers=_auth(user.id))
    request_id = sub.json()["join_request_id"]

    resp = client.post(
        f"/organizations/{org.id}/join-requests/{request_id}/reject",
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    gone = db.query(OrganizationJoinRequest).filter(
        OrganizationJoinRequest.id == request_id,
    ).first()
    assert gone is None

    no_membership = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org.id,
        OrganizationUser.user_id == user.id,
    ).first()
    assert no_membership is None


# ── RESOLVE INVITE CODE ───────────────────────────────────────────────────────

def test_resolve_valid_code(client, db):
    owner = _make_user(db, email="owner@test.com")
    org = _make_org(db, name="Dance Studio")
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id, default_role="member", requires_approval=True)

    resp = client.get(f"/invite-codes/resolve?code={invite.code}", headers=_auth(owner.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["organization_id"] == org.id
    assert data["organization_name"] == "Dance Studio"
    assert data["default_role"] == "member"
    assert data["requires_approval"] is True


def test_resolve_invalid_code(client, db):
    user = _make_user(db)
    resp = client.get("/invite-codes/resolve?code=NOTEXIST", headers=_auth(user.id))
    assert resp.status_code == 404


def test_resolve_inactive_code(client, db):
    owner = _make_user(db, email="owner@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id, is_active=False)

    resp = client.get(f"/invite-codes/resolve?code={invite.code}", headers=_auth(owner.id))
    assert resp.status_code == 400


def test_resolve_expired_code(client, db):
    owner = _make_user(db, email="owner@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    past = datetime.utcnow() - timedelta(days=1)
    invite = _make_invite_code(db, org.id, owner.id, expires_at=past)

    resp = client.get(f"/invite-codes/resolve?code={invite.code}", headers=_auth(owner.id))
    assert resp.status_code == 400


def test_resolve_unauthenticated(client, db):
    owner = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id)

    resp = client.get(f"/invite-codes/resolve?code={invite.code}")
    assert resp.status_code == 401


def test_reject_allows_resubmit(client, db):
    owner = _make_user(db, email="owner@test.com")
    user = _make_user(db, email="user@test.com")
    org = _make_org(db)
    _make_membership(db, org.id, owner.id, role="owner")
    invite = _make_invite_code(db, org.id, owner.id)

    sub = client.post(f"/organizations/{org.id}/join-requests",
                      json={"code": invite.code}, headers=_auth(user.id))
    request_id = sub.json()["join_request_id"]

    client.post(f"/organizations/{org.id}/join-requests/{request_id}/reject",
                headers=_auth(owner.id))

    resp2 = client.post(f"/organizations/{org.id}/join-requests",
                        json={"code": invite.code}, headers=_auth(user.id))
    assert resp2.status_code == 201
