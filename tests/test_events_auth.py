"""
Authorization regression tests for event mutation endpoints.

POST / PUT / DELETE /events/ require org owner/admin or system admin.
The owning org is resolved from the stored event record (never from the update payload).
GET endpoints remain public. Recurring-event scope variants (single/future/series)
respect the same permission model.
"""
from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.event_series import EventSeries
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False):
    u = User(email=email, name="Test", password_hash="x", is_system_admin=is_system_admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, name="Test Org"):
    o = Organization(name=name, status="active", verified=True)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_category(db):
    c = Category(name="Cat")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_membership(db, org_id, user_id, role):
    m = OrganizationUser(organization_id=org_id, user_id=user_id, role=role)
    db.add(m)
    db.commit()
    return m


def _auth(user_id):
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


def _event_body(org_id, cat_id, **kwargs):
    body = {
        "organization_id": org_id,
        "title": "Auth Test Event",
        "start_datetime": "2099-06-01T10:00:00",
        "category_ids": [cat_id],
    }
    body.update(kwargs)
    return body


def _recurring_body(org_id, cat_id):
    return _event_body(org_id, cat_id, recurrence={
        "frequency": "weekly",
        "interval": 1,
        "end_type": "count",
        "total_count": 3,
    })


def _create_event(client, db, user, org, cat):
    """Helper: create a single event as the given user (must be owner/admin)."""
    resp = client.post("/events/", json=_event_body(org.id, cat.id), headers=_auth(user.id))
    assert resp.status_code == 200
    return resp.json()["id"]


def _create_recurring(client, db, user, org, cat):
    """Helper: create a recurring event and return the first occurrence id.

    geocode() returns (None, None) in tests (no API key), which is handled
    gracefully — no mock needed.
    """
    resp = client.post("/events/", json=_recurring_body(org.id, cat.id), headers=_auth(user.id))
    assert resp.status_code == 200
    return resp.json()["id"]


# ── POST /events/ ─────────────────────────────────────────────────────────────

def test_create_event_unauthenticated(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    assert client.post("/events/", json=_event_body(org.id, cat.id)).status_code == 401


def test_create_event_unrelated_user(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    stranger = _make_user(db, "stranger@test.com")
    assert client.post(
        "/events/", json=_event_body(org.id, cat.id), headers=_auth(stranger.id)
    ).status_code == 403


def test_create_event_read_only_member_blocked(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")
    assert client.post(
        "/events/", json=_event_body(org.id, cat.id), headers=_auth(member.id)
    ).status_code == 403


def test_create_event_org_admin_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, admin.id, role="admin")
    resp = client.post("/events/", json=_event_body(org.id, cat.id), headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["title"] == "Auth Test Event"


def test_create_event_org_owner_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    assert client.post("/events/", json=_event_body(org.id, cat.id), headers=_auth(owner.id)).status_code == 200


def test_create_event_system_admin_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    assert client.post("/events/", json=_event_body(org.id, cat.id), headers=_auth(sysadmin.id)).status_code == 200


# ── PUT /events/{id} ──────────────────────────────────────────────────────────

def test_update_event_unauthenticated(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    eid = _create_event(client, db, owner, org, cat)
    assert client.put(f"/events/{eid}", json={"title": "Y"}).status_code == 401


def test_update_event_read_only_member_blocked(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")
    eid = _create_event(client, db, owner, org, cat)
    assert client.put(f"/events/{eid}", json={"title": "Y"}, headers=_auth(member.id)).status_code == 403


def test_update_event_org_admin_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, admin.id, role="admin")
    eid = _create_event(client, db, owner, org, cat)
    resp = client.put(f"/events/{eid}", json={"title": "Updated"}, headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated"


def test_update_event_cross_org_blocked(client, db):
    """An owner of org_a must not update an event belonging to org_b."""
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    cat = _make_category(db)
    owner_a = _make_user(db, "ownera@test.com")
    owner_b = _make_user(db, "ownerb@test.com")
    _make_membership(db, org_a.id, owner_a.id, role="owner")
    _make_membership(db, org_b.id, owner_b.id, role="owner")
    eid_b = _create_event(client, db, owner_b, org_b, cat)
    assert client.put(f"/events/{eid_b}", json={"title": "Y"}, headers=_auth(owner_a.id)).status_code == 403


def test_update_event_system_admin_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    _make_membership(db, org.id, owner.id, role="owner")
    eid = _create_event(client, db, owner, org, cat)
    resp = client.put(f"/events/{eid}", json={"title": "SysUpdated"}, headers=_auth(sysadmin.id))
    assert resp.status_code == 200


# ── DELETE /events/{id} ───────────────────────────────────────────────────────

def test_delete_event_unauthenticated(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    eid = _create_event(client, db, owner, org, cat)
    assert client.delete(f"/events/{eid}").status_code == 401


def test_delete_event_read_only_member_blocked(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")
    eid = _create_event(client, db, owner, org, cat)
    assert client.delete(f"/events/{eid}", headers=_auth(member.id)).status_code == 403


def test_delete_event_org_owner_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    eid = _create_event(client, db, owner, org, cat)
    assert client.delete(f"/events/{eid}", headers=_auth(owner.id)).status_code == 200


def test_delete_event_cross_org_blocked(client, db):
    org_a = _make_org(db, "Org A")
    org_b = _make_org(db, "Org B")
    cat = _make_category(db)
    owner_a = _make_user(db, "ownera@test.com")
    owner_b = _make_user(db, "ownerb@test.com")
    _make_membership(db, org_a.id, owner_a.id, role="owner")
    _make_membership(db, org_b.id, owner_b.id, role="owner")
    eid_b = _create_event(client, db, owner_b, org_b, cat)
    assert client.delete(f"/events/{eid_b}", headers=_auth(owner_a.id)).status_code == 403


def test_delete_event_system_admin_allowed(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    _make_membership(db, org.id, owner.id, role="owner")
    eid = _create_event(client, db, owner, org, cat)
    assert client.delete(f"/events/{eid}", headers=_auth(sysadmin.id)).status_code == 200


# ── GET events remain public ──────────────────────────────────────────────────

def test_get_events_is_public(client, db):
    assert client.get("/events/").status_code == 200


def test_get_event_by_id_is_public(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    eid = _create_event(client, db, owner, org, cat)
    assert client.get(f"/events/{eid}").status_code == 200


# ── Recurring event permission checks ─────────────────────────────────────────

def test_update_recurring_event_member_blocked(client, db):
    """A member must not update any scope of a recurring event."""
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")
    eid = _create_recurring(client, db, owner, org, cat)
    for scope in ("single", "future", "series"):
        resp = client.put(
            f"/events/{eid}",
            json={"title": "Hacked"},
            params={"scope": scope},
            headers=_auth(member.id),
        )
        assert resp.status_code == 403, f"scope={scope} should be blocked for member"


def test_update_recurring_event_owner_allowed_single(client, db):
    """An org owner can update a single occurrence of a recurring event."""
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    eid = _create_recurring(client, db, owner, org, cat)
    resp = client.put(
        f"/events/{eid}",
        json={"title": "Updated Single"},
        params={"scope": "single"},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200


def test_update_recurring_event_owner_allowed_series(client, db):
    """An org owner can update all occurrences (scope=series)."""
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    eid = _create_recurring(client, db, owner, org, cat)
    resp = client.put(
        f"/events/{eid}",
        json={"title": "Updated Series"},
        params={"scope": "series"},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200


def test_delete_recurring_event_member_blocked(client, db):
    """A member must not delete any scope of a recurring event."""
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    _make_membership(db, org.id, member.id, role="member")
    eid = _create_recurring(client, db, owner, org, cat)
    resp = client.delete(
        f"/events/{eid}",
        params={"scope": "series"},
        headers=_auth(member.id),
    )
    assert resp.status_code == 403


def test_delete_recurring_event_owner_allowed_series(client, db):
    """An org owner can delete an entire recurring series (scope=series)."""
    org = _make_org(db)
    cat = _make_category(db)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")
    eid = _create_recurring(client, db, owner, org, cat)
    resp = client.delete(
        f"/events/{eid}",
        params={"scope": "series"},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200
