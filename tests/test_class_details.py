"""
Regression tests for GET /classes/{class_id}/details.

Finding: null dereference crash when class_id does not exist or its
organization has been deleted. Both cases must return 404, not 500.
"""
import datetime
import pytest

from app.core.security import create_access_token
from app.models.category import Category
from app.models.classes import Class
from app.models.group import Group
from app.models.group_schedule import GroupSchedule
from app.models.organization import Organization
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_org(db, name="Det Org"):
    o = Organization(name=name, status="active")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_category(db):
    c = Category(name="TestCat")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_class(db, org_id, cat_id, name="Test Class"):
    c = Class(organization_id=org_id, category_id=cat_id, name=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_group(db, class_id, name="Group A"):
    g = Group(class_id=class_id, name=name, age_from=5, age_to=10)
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


# ── Null-dereference regression tests ────────────────────────────────────────

def test_class_details_nonexistent_id_returns_404(client, db):
    """
    Regression: before the fix, GET /classes/999999/details crashed with
    AttributeError on class_obj.organization_id and returned 500.
    Must return 404.
    """
    resp = client.get("/classes/999999/details")
    assert resp.status_code == 404


def test_class_details_orphaned_organization_returns_404(client, db):
    """
    Regression: before the fix, GET /classes/{id}/details when the owning
    organization has been deleted crashed on organization.id and returned 500.
    Must return 404.
    """
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)

    # Delete the organization after the class was created — orphaned class.
    db.delete(org)
    db.commit()

    resp = client.get(f"/classes/{cls.id}/details")
    assert resp.status_code == 404


# ── Valid request still works ─────────────────────────────────────────────────

def test_class_details_valid_id_returns_200(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)

    resp = client.get(f"/classes/{cls.id}/details")
    assert resp.status_code == 200
    body = resp.json()
    assert body["class"]["id"] == cls.id
    assert body["class"]["name"] == "Test Class"
    assert body["organization"]["id"] == org.id


def test_class_details_includes_groups_and_schedules(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)
    group = _make_group(db, cls.id)
    schedule = GroupSchedule(
        group_id=group.id,
        day_of_week=1,
        start_time=datetime.time(10, 0),
        end_time=datetime.time(11, 0),
    )
    db.add(schedule)
    db.commit()

    resp = client.get(f"/classes/{cls.id}/details")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["groups"]) == 1
    assert body["groups"][0]["id"] == group.id
    assert len(body["schedules"]) == 1


def test_class_details_no_groups_returns_empty_lists(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    cls = _make_class(db, org.id, cat.id)

    resp = client.get(f"/classes/{cls.id}/details")
    assert resp.status_code == 200
    body = resp.json()
    assert body["groups"] == []
    assert body["schedules"] == []
    assert body["rating"] is None
