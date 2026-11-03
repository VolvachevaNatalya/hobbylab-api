"""
Regression tests for unbounded list endpoints — Task 20.

Fixed endpoints:
  GET /classes/search              server-side cap at 100 (was uncapped)
  GET /groups/                     limit/offset params added, cap at 500
  GET /group-schedules/            limit/offset params added, cap at 500
  GET /reviews/organization/{id}   limit/offset added, cap at 100,
                                   restricted to status="active" only

All existing response structures are preserved (flat lists).
"""
import datetime

import pytest

from app.core.security import create_access_token, hash_password
from app.models.category import Category
from app.models.classes import Class
from app.models.group import Group
from app.models.group_schedule import GroupSchedule
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.review import Review
from app.models.user import User


# ── shared helpers ────────────────────────────────────────────────────────────

def _make_user(db, email, status="active"):
    u = User(email=email, name="T", password_hash=hash_password("pw"), status=status)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, name="Org"):
    o = Organization(name=name, status="active", verified=True)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_class(db, org_id, name="Class"):
    cat = Category(name=f"Cat-{name}")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    c = Class(organization_id=org_id, category_id=cat.id, name=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_group(db, class_id, name="Group"):
    g = Group(class_id=class_id, name=name)
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


def _make_schedule(db, group_id, day=1):
    s = GroupSchedule(
        group_id=group_id,
        day_of_week=day,
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _make_review(db, org_id, user_id, rating=5, status="active", created_at=None):
    kwargs = {}
    if created_at is not None:
        kwargs["created_at"] = created_at
    r = Review(user_id=user_id, organization_id=org_id, rating=rating, status=status, **kwargs)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _auth(user_id):
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


# ── GET /classes/search ────────────────────────────────────────────────────────

def test_search_classes_requires_auth(client, db):
    assert client.get("/classes/search").status_code == 401


def test_search_classes_default_limit_in_response(client, db):
    """Response includes limit=20 by default."""
    user = _make_user(db, "sc_default@t.com")
    resp = client.get("/classes/search", headers=_auth(user.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert isinstance(data["items"], list)


def test_search_classes_custom_limit_respected(client, db):
    """limit=3 with 5 classes → items list has at most 3 entries."""
    user = _make_user(db, "sc_limit@t.com")
    org = _make_org(db)
    for i in range(5):
        _make_class(db, org.id, name=f"C{i}")
    resp = client.get("/classes/search?limit=3", headers=_auth(user.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 3
    assert len(data["items"]) <= 3


def test_search_classes_offset_works(client, db):
    """offset=2 with 3 classes → fewer items than offset=0."""
    user = _make_user(db, "sc_offset@t.com")
    org = _make_org(db)
    for i in range(3):
        _make_class(db, org.id, name=f"C{i}")
    resp0 = client.get("/classes/search?limit=10&offset=0", headers=_auth(user.id))
    resp2 = client.get("/classes/search?limit=10&offset=2", headers=_auth(user.id))
    assert resp0.status_code == 200
    assert resp2.status_code == 200
    assert len(resp0.json()["items"]) > len(resp2.json()["items"])


def test_search_classes_limit_capped_at_100(client, db):
    """
    Regression: passing limit=9999 must be silently clamped to 100.
    The response 'limit' field reflects the server-side cap.
    """
    user = _make_user(db, "sc_cap@t.com")
    resp = client.get("/classes/search?limit=9999", headers=_auth(user.id))
    assert resp.status_code == 200
    assert resp.json()["limit"] == 100


def test_search_classes_limit_zero_clamped_to_one(client, db):
    """limit=0 is clamped to 1 rather than raising an error."""
    user = _make_user(db, "sc_zero@t.com")
    resp = client.get("/classes/search?limit=0", headers=_auth(user.id))
    assert resp.status_code == 200
    assert resp.json()["limit"] == 1


# ── GET /groups/ ───────────────────────────────────────────────────────────────

def test_get_groups_returns_flat_list(client, db):
    """Response structure is preserved — flat list, not a dict."""
    org = _make_org(db)
    cls = _make_class(db, org.id)
    _make_group(db, cls.id)
    resp = client.get("/groups/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_groups_default_returns_all_when_few(client, db):
    """Three groups are returned when no pagination params supplied."""
    org = _make_org(db)
    cls = _make_class(db, org.id)
    for i in range(3):
        _make_group(db, cls.id, name=f"G{i}")
    resp = client.get("/groups/")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_get_groups_limit_respected(client, db):
    """limit=2 with 5 groups → 2 returned."""
    org = _make_org(db)
    cls = _make_class(db, org.id)
    for i in range(5):
        _make_group(db, cls.id, name=f"G{i}")
    resp = client.get("/groups/?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_groups_offset_respected(client, db):
    """offset=3 with 5 groups → 2 returned."""
    org = _make_org(db)
    cls = _make_class(db, org.id)
    for i in range(5):
        _make_group(db, cls.id, name=f"G{i}")
    resp = client.get("/groups/?offset=3")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_groups_large_limit_does_not_crash(client, db):
    """limit=99999 does not raise a server error and returns a flat list."""
    org = _make_org(db)
    cls = _make_class(db, org.id)
    _make_group(db, cls.id)
    resp = client.get("/groups/?limit=99999")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_groups_limit_offset_combination(client, db):
    """limit=2&offset=1 with 4 groups → exactly 2 groups."""
    org = _make_org(db)
    cls = _make_class(db, org.id)
    for i in range(4):
        _make_group(db, cls.id, name=f"G{i}")
    resp = client.get("/groups/?limit=2&offset=1")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# ── GET /group-schedules/ ─────────────────────────────────────────────────────

def test_get_group_schedules_returns_flat_list(client, db):
    """Response structure is preserved — flat list."""
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    _make_schedule(db, grp.id)
    resp = client.get("/group-schedules/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_group_schedules_default_returns_all_when_few(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    for day in range(1, 4):
        _make_schedule(db, grp.id, day=day)
    resp = client.get("/group-schedules/")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_get_group_schedules_limit_respected(client, db):
    """limit=2 with 5 schedules → 2 returned."""
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    for day in range(1, 6):
        _make_schedule(db, grp.id, day=day)
    resp = client.get("/group-schedules/?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_group_schedules_offset_respected(client, db):
    """offset=4 with 5 schedules → 1 returned."""
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    for day in range(1, 6):
        _make_schedule(db, grp.id, day=day)
    resp = client.get("/group-schedules/?offset=4")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_group_schedules_large_limit_does_not_crash(client, db):
    org = _make_org(db)
    cls = _make_class(db, org.id)
    grp = _make_group(db, cls.id)
    _make_schedule(db, grp.id)
    resp = client.get("/group-schedules/?limit=99999")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── GET /reviews/organization/{id} ────────────────────────────────────────────
# Returns a flat JSON array — original contract preserved for backward compatibility
# with all previously released Flutter app versions.

def test_get_reviews_returns_flat_list(client, db):
    """Response structure is preserved — flat list (original contract)."""
    org = _make_org(db)
    user = _make_user(db, "rv_list@t.com")
    _make_review(db, org.id, user.id)
    resp = client.get(f"/reviews/organization/{org.id}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_reviews_only_active_returned(client, db):
    """
    Regression: before the fix all statuses were returned.
    After the fix only status='active' reviews appear.
    """
    org = _make_org(db)
    u1 = _make_user(db, "rv_act@t.com")
    u2 = _make_user(db, "rv_pend@t.com")
    u3 = _make_user(db, "rv_rej@t.com")
    active = _make_review(db, org.id, u1.id, rating=5, status="active")
    _make_review(db, org.id, u2.id, rating=3, status="pending")
    _make_review(db, org.id, u3.id, rating=1, status="rejected")
    resp = client.get(f"/reviews/organization/{org.id}")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert active.id in ids
    assert len(ids) == 1


def test_get_reviews_pending_not_exposed(client, db):
    """Pending reviews must not appear in public listing."""
    org = _make_org(db)
    user = _make_user(db, "rv_pend2@t.com")
    _make_review(db, org.id, user.id, rating=4, status="pending")
    resp = client.get(f"/reviews/organization/{org.id}")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_reviews_rejected_not_exposed(client, db):
    org = _make_org(db)
    user = _make_user(db, "rv_rej2@t.com")
    _make_review(db, org.id, user.id, rating=2, status="rejected")
    resp = client.get(f"/reviews/organization/{org.id}")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_reviews_limit_respected(client, db):
    """limit=2 with 4 active reviews → 2 returned."""
    org = _make_org(db)
    users = [_make_user(db, f"rv_lim{i}@t.com") for i in range(4)]
    for u in users:
        _make_review(db, org.id, u.id)
    resp = client.get(f"/reviews/organization/{org.id}?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_reviews_offset_respected(client, db):
    """offset=3 with 4 active reviews → 1 returned."""
    org = _make_org(db)
    users = [_make_user(db, f"rv_off{i}@t.com") for i in range(4)]
    for u in users:
        _make_review(db, org.id, u.id)
    resp = client.get(f"/reviews/organization/{org.id}?offset=3")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_reviews_limit_capped_at_100(client, db):
    """limit=9999 silently capped; returns all 3 reviews without crashing."""
    org = _make_org(db)
    users = [_make_user(db, f"rv_cap{i}@t.com") for i in range(3)]
    for u in users:
        _make_review(db, org.id, u.id)
    resp = client.get(f"/reviews/organization/{org.id}?limit=9999")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_get_reviews_limit_zero_clamped_to_one(client, db):
    """limit=0 is silently clamped to 1."""
    org = _make_org(db)
    users = [_make_user(db, f"rv_zero{i}@t.com") for i in range(3)]
    for u in users:
        _make_review(db, org.id, u.id)
    resp = client.get(f"/reviews/organization/{org.id}?limit=0")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_reviews_empty_org(client, db):
    org = _make_org(db)
    resp = client.get(f"/reviews/organization/{org.id}")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_reviews_ordered_newest_first(client, db):
    """Reviews are returned newest first. Uses explicit timestamps to avoid SQLite ties."""
    org = _make_org(db)
    u1 = _make_user(db, "rv_ord1@t.com")
    u2 = _make_user(db, "rv_ord2@t.com")
    r1 = _make_review(
        db, org.id, u1.id, rating=4,
        created_at=datetime.datetime(2024, 1, 1, 12, 0, 0),
    )
    r2 = _make_review(
        db, org.id, u2.id, rating=5,
        created_at=datetime.datetime(2024, 1, 2, 12, 0, 0),
    )
    resp = client.get(f"/reviews/organization/{org.id}")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert ids.index(r2.id) < ids.index(r1.id)


# ── GET /reviews/organization/{id}/stats ──────────────────────────────────────
# Separate endpoint for accurate aggregate data (total count + average rating)
# computed over ALL active reviews regardless of any pagination limit.
# New Flutter versions call this alongside the reviews list endpoint.

def test_review_stats_empty_org(client, db):
    """Stats for org with no reviews: total=0, average_rating=null."""
    org = _make_org(db)
    resp = client.get(f"/reviews/organization/{org.id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["average_rating"] is None


def test_review_stats_basic(client, db):
    """Stats reflect all active reviews for the org."""
    org = _make_org(db)
    u1 = _make_user(db, "st_u1@t.com")
    u2 = _make_user(db, "st_u2@t.com")
    _make_review(db, org.id, u1.id, rating=4)
    _make_review(db, org.id, u2.id, rating=2)
    resp = client.get(f"/reviews/organization/{org.id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["average_rating"] == pytest.approx(3.0, abs=0.01)


def test_review_stats_excludes_non_active(client, db):
    """Pending and rejected reviews are excluded from total and average."""
    org = _make_org(db)
    u1 = _make_user(db, "st_excl1@t.com")
    u2 = _make_user(db, "st_excl2@t.com")
    u3 = _make_user(db, "st_excl3@t.com")
    _make_review(db, org.id, u1.id, rating=5, status="active")
    _make_review(db, org.id, u2.id, rating=1, status="pending")
    _make_review(db, org.id, u3.id, rating=1, status="rejected")
    resp = client.get(f"/reviews/organization/{org.id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["average_rating"] == pytest.approx(5.0, abs=0.01)


def test_review_stats_covers_beyond_default_limit(client, db):
    """
    Stats total is accurate even when review count exceeds the list endpoint's
    default limit. This is the core regression guard: the list endpoint is
    paginated, but stats must reflect every review.
    """
    org = _make_org(db)
    users = [_make_user(db, f"st_big{i}@t.com") for i in range(5)]
    for u in users:
        _make_review(db, org.id, u.id, rating=4)
    # List endpoint with limit=2 returns 2 items, but stats must show 5
    list_resp = client.get(f"/reviews/organization/{org.id}?limit=2")
    assert len(list_resp.json()) == 2
    stats_resp = client.get(f"/reviews/organization/{org.id}/stats")
    assert stats_resp.status_code == 200
    assert stats_resp.json()["total"] == 5


def test_review_stats_average_computed_correctly(client, db):
    """Average is the mean of all active ratings, rounded to 2 decimal places."""
    org = _make_org(db)
    u1 = _make_user(db, "st_avg1@t.com")
    u2 = _make_user(db, "st_avg2@t.com")
    u3 = _make_user(db, "st_avg3@t.com")
    _make_review(db, org.id, u1.id, rating=3)
    _make_review(db, org.id, u2.id, rating=4)
    _make_review(db, org.id, u3.id, rating=5)
    resp = client.get(f"/reviews/organization/{org.id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["average_rating"] == pytest.approx(4.0, abs=0.01)


def test_review_stats_isolated_per_org(client, db):
    """Stats for one org are not polluted by reviews on another org."""
    org_a = _make_org(db)
    org_b = _make_org(db)
    u1 = _make_user(db, "st_iso1@t.com")
    u2 = _make_user(db, "st_iso2@t.com")
    _make_review(db, org_a.id, u1.id, rating=5)
    _make_review(db, org_b.id, u2.id, rating=1)
    resp = client.get(f"/reviews/organization/{org_a.id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["average_rating"] == pytest.approx(5.0, abs=0.01)
