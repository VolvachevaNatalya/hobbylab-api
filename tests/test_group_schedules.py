"""
Authorization tests for /group-schedules/ endpoints.

Ownership chain: GroupSchedule → Group → Class → Organization
Allowed to mutate: org owners, org admins, system admins.
Blocked: unauthenticated, unrelated users, org members with role="member".
Read endpoints remain public.
"""
from datetime import time

from app.core.security import create_access_token
from app.models.category import Category
from app.models.classes import Class
from app.models.group import Group
from app.models.group_schedule import GroupSchedule
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False):
    u = User(email=email, name="Test", password_hash="x", is_system_admin=is_system_admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db):
    o = Organization(name="Test Org", status="active")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_membership(db, org_id, user_id, role):
    m = OrganizationUser(organization_id=org_id, user_id=user_id, role=role)
    db.add(m)
    db.commit()
    return m


def _make_class(db, org_id):
    cat = Category(name="Cat")
    db.add(cat)
    db.flush()
    c = Class(organization_id=org_id, category_id=cat.id, name="Test Class")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_group(db, class_id):
    g = Group(class_id=class_id, name="Test Group")
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


def _make_schedule(db, group_id):
    s = GroupSchedule(group_id=group_id, day_of_week=1, start_time=time(9, 0), end_time=time(10, 0))
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


_SCHEDULE_PAYLOAD = {
    "day_of_week": 2,
    "start_time": "10:00:00",
    "end_time": "11:00:00",
}


# ── Read endpoints remain public ──────────────────────────────────────────────

def test_list_all_schedules_is_public(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    _make_schedule(db, grp.id)

    resp = client.get("/group-schedules/")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_schedules_by_group_is_public(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    _make_schedule(db, grp.id)

    resp = client.get(f"/group-schedules/group/{grp.id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# ── Unauthenticated requests are rejected ─────────────────────────────────────

def test_create_schedule_unauthenticated(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)

    resp = client.post("/group-schedules/", json={"group_id": grp.id, **_SCHEDULE_PAYLOAD})
    assert resp.status_code == 401


def test_update_schedule_unauthenticated(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sched = _make_schedule(db, grp.id)

    resp = client.put(f"/group-schedules/{sched.id}", json={"day_of_week": 3})
    assert resp.status_code == 401


def test_delete_schedule_unauthenticated(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sched = _make_schedule(db, grp.id)

    resp = client.delete(f"/group-schedules/{sched.id}")
    assert resp.status_code == 401


# ── Unrelated users are rejected ─────────────────────────────────────────────

def test_create_schedule_unrelated_user_is_rejected(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    stranger = _make_user(db, "stranger@test.com")

    resp = client.post(
        "/group-schedules/",
        json={"group_id": grp.id, **_SCHEDULE_PAYLOAD},
        headers=_auth(stranger.id),
    )
    assert resp.status_code == 403


def test_update_schedule_unrelated_user_is_rejected(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sched = _make_schedule(db, grp.id)
    stranger = _make_user(db, "stranger@test.com")

    resp = client.put(
        f"/group-schedules/{sched.id}",
        json={"day_of_week": 3},
        headers=_auth(stranger.id),
    )
    assert resp.status_code == 403


def test_delete_schedule_unrelated_user_is_rejected(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sched = _make_schedule(db, grp.id)
    stranger = _make_user(db, "stranger@test.com")

    resp = client.delete(f"/group-schedules/{sched.id}", headers=_auth(stranger.id))
    assert resp.status_code == 403


# ── Org members with role="member" (read-only) are rejected ──────────────────

def test_create_schedule_readonly_member_is_rejected(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.post(
        "/group-schedules/",
        json={"group_id": grp.id, **_SCHEDULE_PAYLOAD},
        headers=_auth(member.id),
    )
    assert resp.status_code == 403


def test_update_schedule_readonly_member_is_rejected(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sched = _make_schedule(db, grp.id)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.put(
        f"/group-schedules/{sched.id}",
        json={"day_of_week": 3},
        headers=_auth(member.id),
    )
    assert resp.status_code == 403


def test_delete_schedule_readonly_member_is_rejected(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sched = _make_schedule(db, grp.id)
    member = _make_user(db, "member@test.com")
    _make_membership(db, org.id, member.id, role="member")

    resp = client.delete(f"/group-schedules/{sched.id}", headers=_auth(member.id))
    assert resp.status_code == 403


# ── Org admins can mutate ────────────────────────────────────────────────────

def test_create_schedule_org_admin_succeeds(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, admin.id, role="admin")

    resp = client.post(
        "/group-schedules/",
        json={"group_id": grp.id, **_SCHEDULE_PAYLOAD},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["group_id"] == grp.id


def test_update_schedule_org_admin_succeeds(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sched = _make_schedule(db, grp.id)
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, admin.id, role="admin")

    resp = client.put(
        f"/group-schedules/{sched.id}",
        json={"day_of_week": 5},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["day_of_week"] == 5


def test_delete_schedule_org_admin_succeeds(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sched = _make_schedule(db, grp.id)
    admin = _make_user(db, "admin@test.com")
    _make_membership(db, org.id, admin.id, role="admin")

    resp = client.delete(f"/group-schedules/{sched.id}", headers=_auth(admin.id))
    assert resp.status_code == 200


# ── Org owners can mutate ────────────────────────────────────────────────────

def test_create_schedule_org_owner_succeeds(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    owner = _make_user(db, "owner@test.com")
    _make_membership(db, org.id, owner.id, role="owner")

    resp = client.post(
        "/group-schedules/",
        json={"group_id": grp.id, **_SCHEDULE_PAYLOAD},
        headers=_auth(owner.id),
    )
    assert resp.status_code == 200


# ── System admins can mutate any org's schedules ──────────────────────────────

def test_create_schedule_system_admin_succeeds(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)

    resp = client.post(
        "/group-schedules/",
        json={"group_id": grp.id, **_SCHEDULE_PAYLOAD},
        headers=_auth(sysadmin.id),
    )
    assert resp.status_code == 200


def test_update_schedule_system_admin_succeeds(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sched = _make_schedule(db, grp.id)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)

    resp = client.put(
        f"/group-schedules/{sched.id}",
        json={"day_of_week": 6},
        headers=_auth(sysadmin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["day_of_week"] == 6


def test_delete_schedule_system_admin_succeeds(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    sched = _make_schedule(db, grp.id)
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)

    resp = client.delete(f"/group-schedules/{sched.id}", headers=_auth(sysadmin.id))
    assert resp.status_code == 200


# ── 404 on missing resources ─────────────────────────────────────────────────

def test_update_nonexistent_schedule_returns_404(client, db):
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    resp = client.put("/group-schedules/99999", json={"day_of_week": 1}, headers=_auth(sysadmin.id))
    assert resp.status_code == 404


def test_delete_nonexistent_schedule_returns_404(client, db):
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    resp = client.delete("/group-schedules/99999", headers=_auth(sysadmin.id))
    assert resp.status_code == 404


def test_create_schedule_nonexistent_group_returns_404(client, db):
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    resp = client.post(
        "/group-schedules/",
        json={"group_id": 99999, **_SCHEDULE_PAYLOAD},
        headers=_auth(sysadmin.id),
    )
    assert resp.status_code == 404
