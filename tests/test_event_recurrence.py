from datetime import datetime, timedelta

import pytest

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.event_series import EventSeries
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_user(db, email="user@test.com"):
    user = User(email=email, name="Test User", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_org(db):
    org = Organization(name="Test Org", status="active", verified=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _make_membership(db, org_id, user_id):
    row = OrganizationUser(organization_id=org_id, user_id=user_id, role="owner")
    db.add(row)
    db.commit()
    return row


def _make_category(db, name="Dance"):
    cat = Category(name=name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


def _event_body(org_id, category_ids, start="2026-08-03T10:00:00", **kwargs):
    body = {
        "organization_id": org_id,
        "title": "Recurring Event",
        "start_datetime": start,
        "category_ids": category_ids,
    }
    body.update(kwargs)
    return body


def _recurrence(frequency, interval, end_type, total_count=None, end_date=None):
    r = {"frequency": frequency, "interval": interval, "end_type": end_type}
    if total_count is not None:
        r["total_count"] = total_count
    if end_date is not None:
        r["end_date"] = str(end_date)
    return r


def _series_count(db, series_id):
    return db.query(Event).filter(Event.series_id == series_id).count()


# ── 1. Count-bounded series creation ──────────────────────────────────────────

def test_create_recurring_count_bounded(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=4))
    resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert resp.status_code == 200

    data = resp.json()
    series_id = data["series_id"]
    assert series_id is not None
    assert data["occurrence_index"] == 0
    assert _series_count(db, series_id) == 4


# ── 2. total_count < 2 is rejected ────────────────────────────────────────────

def test_create_recurring_total_count_1_rejected(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=1))
    resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert resp.status_code == 422


# ── 3. Date-bounded series creation ───────────────────────────────────────────

def test_create_recurring_date_bounded(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    # Weekly from Aug 3 with end_date Aug 17 → Aug 3, Aug 10, Aug 17 = 3 events
    body = _event_body(
        org.id, [cat.id],
        start="2026-08-03T10:00:00",
        recurrence=_recurrence("weekly", 1, "date", end_date="2026-08-17"),
    )
    resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert resp.status_code == 200

    series_id = resp.json()["series_id"]
    assert _series_count(db, series_id) == 3


# ── 4. Never-ending series stops at 12 months ─────────────────────────────────

def test_create_recurring_never_stops_at_12_months(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    # Weekly never: ~52–53 occurrences in 12 months
    body = _event_body(
        org.id, [cat.id],
        start="2026-08-03T10:00:00",
        recurrence=_recurrence("weekly", 1, "never"),
    )
    resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert resp.status_code == 200

    series_id = resp.json()["series_id"]
    count = _series_count(db, series_id)
    assert count >= 52
    assert count <= 54


# ── 5. POST returns first occurrence ──────────────────────────────────────────

def test_recurring_post_returns_first_occurrence(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=3))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    assert data["occurrence_index"] == 0
    assert data["start_datetime"] == "2026-08-03T10:00:00"


# ── 6. Response includes populated recurrence field ───────────────────────────

def test_recurring_event_response_has_recurrence_field(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("monthly", 1, "count", total_count=3))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    assert data["recurrence"] is not None
    assert data["recurrence"]["frequency"] == "monthly"
    assert data["recurrence"]["total_count"] == 3


# ── 7. GET single event includes recurrence ───────────────────────────────────

def test_get_event_includes_recurrence(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 2, "count", total_count=2))
    event_id = client.post("/events/", json=body, headers=_auth(user.id)).json()["id"]

    resp = client.get(f"/events/{event_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recurrence"]["frequency"] == "weekly"
    assert data["recurrence"]["interval"] == 2


# ── 8. GET list includes recurrence ───────────────────────────────────────────

def test_list_events_includes_recurrence(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=2))
    client.post("/events/", json=body, headers=_auth(user.id))

    resp = client.get("/events/", params={"organization_id": org.id})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    for item in items:
        assert item["recurrence"] is not None


# ── 9. generated_until is set on creation ────────────────────────────────────

def test_generated_until_set_on_creation(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=3))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()

    series = db.query(EventSeries).filter(EventSeries.id == data["series_id"]).first()
    assert series.generated_until is not None
    # Last occurrence should be 2 weeks after start (index 2)
    expected = datetime(2026, 8, 17, 10, 0, 0)
    assert series.generated_until == expected


# ── 10. DELETE scope=single removes one occurrence ───────────────────────────

def test_delete_scope_single(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=3))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    series_id = data["series_id"]

    # Get the second event (occurrence_index=1)
    second = db.query(Event).filter(
        Event.series_id == series_id, Event.occurrence_index == 1
    ).first()

    resp = client.delete(f"/events/{second.id}", params={"scope": "single"}, headers=_auth(user.id))
    assert resp.status_code == 200
    assert _series_count(db, series_id) == 2


# ── 11. DELETE scope=future removes from index onward ────────────────────────

def test_delete_scope_future(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=4))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    series_id = data["series_id"]

    second = db.query(Event).filter(
        Event.series_id == series_id, Event.occurrence_index == 1
    ).first()

    resp = client.delete(f"/events/{second.id}", params={"scope": "future"}, headers=_auth(user.id))
    assert resp.status_code == 200
    assert _series_count(db, series_id) == 1

    remaining = db.query(Event).filter(Event.series_id == series_id).first()
    assert remaining.occurrence_index == 0


# ── 12. DELETE scope=series removes all + series row ────────────────────────

def test_delete_scope_series(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=3))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    series_id = data["series_id"]
    event_id = data["id"]

    resp = client.delete(f"/events/{event_id}", params={"scope": "series"}, headers=_auth(user.id))
    assert resp.status_code == 200
    assert _series_count(db, series_id) == 0
    assert db.query(EventSeries).filter(EventSeries.id == series_id).first() is None


# ── 13. UPDATE scope=single rejects recurrence change ────────────────────────

def test_update_scope_single_rejects_recurrence_change(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=3))
    event_id = client.post("/events/", json=body, headers=_auth(user.id)).json()["id"]

    resp = client.put(
        f"/events/{event_id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=5)},
        params={"scope": "single"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 400


# ── 14. UPDATE scope=single updates only selected event ──────────────────────

def test_update_scope_single_updates_only_selected(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=3))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    series_id = data["series_id"]

    second = db.query(Event).filter(
        Event.series_id == series_id, Event.occurrence_index == 1
    ).first()

    resp = client.put(
        f"/events/{second.id}",
        json={"title": "Changed"},
        params={"scope": "single"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    events = db.query(Event).filter(Event.series_id == series_id).order_by(Event.occurrence_index).all()
    assert events[0].title == "Recurring Event"
    assert events[1].title == "Changed"
    assert events[2].title == "Recurring Event"


# ── 15. UPDATE scope=future (no recurrence change) leaves past unchanged ─────

def test_update_scope_future_no_recurrence_change(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=3))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    series_id = data["series_id"]

    second = db.query(Event).filter(
        Event.series_id == series_id, Event.occurrence_index == 1
    ).first()

    resp = client.put(
        f"/events/{second.id}",
        json={"title": "Future Title"},
        params={"scope": "future"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    # Occurrence 0 must still be in original series with original title
    first = db.query(Event).filter(
        Event.series_id == series_id, Event.occurrence_index == 0
    ).first()
    assert first is not None
    assert first.title == "Recurring Event"

    # Occurrences 1+ have new title in a new series
    new_series_id = resp.json()["series_id"]
    assert new_series_id != series_id
    future_events = db.query(Event).filter(Event.series_id == new_series_id).all()
    assert len(future_events) == 2
    for e in future_events:
        assert e.title == "Future Title"


# ── 16. UPDATE scope=future with new recurrence regenerates from new rule ─────

def test_update_scope_future_with_new_recurrence(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    # Weekly × 4 → Aug 3, 10, 17, 24
    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=4))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    series_id = data["series_id"]

    # Take occurrence index 2 (Aug 17) and switch to daily × 2 from that date
    occ2 = db.query(Event).filter(
        Event.series_id == series_id, Event.occurrence_index == 2
    ).first()

    resp = client.put(
        f"/events/{occ2.id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=2)},
        params={"scope": "future"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    # Original series now has only 2 events (indices 0 and 1)
    assert _series_count(db, series_id) == 2

    # New series has 2 events starting from Aug 17, daily
    new_series_id = resp.json()["series_id"]
    assert new_series_id != series_id
    new_events = db.query(Event).filter(Event.series_id == new_series_id).order_by(Event.occurrence_index).all()
    assert len(new_events) == 2
    assert new_events[0].start_datetime == datetime(2026, 8, 17, 10, 0, 0)
    assert new_events[1].start_datetime == datetime(2026, 8, 18, 10, 0, 0)


# ── 17. UPDATE scope=series changes all events ────────────────────────────────

def test_update_scope_series_changes_all(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=3))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    series_id = data["series_id"]
    event_id = data["id"]

    resp = client.put(
        f"/events/{event_id}",
        json={"title": "Series Title"},
        params={"scope": "series"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    events = db.query(Event).filter(Event.series_id == series_id).all()
    assert all(e.title == "Series Title" for e in events)


# ── 18. UPDATE scope=series with new recurrence regenerates all ───────────────

def test_update_scope_series_with_new_recurrence(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    # Weekly × 4 → Aug 3, 10, 17, 24
    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=4))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    series_id = data["series_id"]
    event_id = data["id"]

    # Switch to daily × 3 — should delete all 4 and regenerate 3 daily events
    resp = client.put(
        f"/events/{event_id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=3)},
        params={"scope": "series"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    events = db.query(Event).filter(Event.series_id == series_id).order_by(Event.occurrence_index).all()
    assert len(events) == 3
    assert events[0].start_datetime == datetime(2026, 8, 3, 10, 0, 0)
    assert events[1].start_datetime == datetime(2026, 8, 4, 10, 0, 0)
    assert events[2].start_datetime == datetime(2026, 8, 5, 10, 0, 0)


# ── 19. Split at last count occurrence → standalone ───────────────────────────

def test_split_at_last_count_occurrence_becomes_standalone(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    # 2-occurrence series → index 0 stays in series, index 1 is the "last"
    body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=2))
    data = client.post("/events/", json=body, headers=_auth(user.id)).json()
    series_id = data["series_id"]

    last_event = db.query(Event).filter(
        Event.series_id == series_id, Event.occurrence_index == 1
    ).first()

    resp = client.put(
        f"/events/{last_event.id}",
        json={"title": "Standalone Now"},
        params={"scope": "future"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    result = db.query(Event).filter(Event.id == last_event.id).first()
    assert result.series_id is None
    assert result.occurrence_index is None
    assert result.title == "Standalone Now"


# ── 20. Standalone events unaffected by series delete ────────────────────────

def test_standalone_events_unaffected_by_series_delete(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    # Create a standalone event
    solo_body = _event_body(org.id, [cat.id], title="Solo Event", start="2026-09-01T09:00:00")
    solo_id = client.post("/events/", json=solo_body, headers=_auth(user.id)).json()["id"]

    # Create a recurring series
    series_body = _event_body(org.id, [cat.id], recurrence=_recurrence("weekly", 1, "count", total_count=2))
    series_first_id = client.post("/events/", json=series_body, headers=_auth(user.id)).json()["id"]

    # Delete the series
    resp = client.delete(f"/events/{series_first_id}", params={"scope": "series"}, headers=_auth(user.id))
    assert resp.status_code == 200

    # Standalone event must still exist
    solo_resp = client.get(f"/events/{solo_id}")
    assert solo_resp.status_code == 200
    assert solo_resp.json()["title"] == "Solo Event"
