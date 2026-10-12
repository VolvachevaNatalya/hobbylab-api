"""Tests for recurrence-rebuild rules:
- Past occurrences are never modified.
- Future occurrences are deleted and regenerated from the new recurrence rule.
- Rebuild starts at the earliest upcoming (future) occurrence.
- The EventSeries row is updated in place — no new series is ever created.
- Total count is preserved when only frequency/interval changes.
"""

from datetime import datetime

import pytest

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.event_series import EventSeries
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User

# Anchor dates — stable regardless of when the test runs.
_PAST_1 = datetime(2026, 9, 1, 10, 0)   # well before Oct 2026
_PAST_2 = datetime(2026, 9, 8, 10, 0)
_FUT_1 = datetime(2099, 1, 7, 10, 0)    # far future (Monday)
_FUT_2 = datetime(2099, 1, 14, 10, 0)
_FUT_3 = datetime(2099, 1, 21, 10, 0)
_FUT_4 = datetime(2099, 1, 28, 10, 0)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_user(db, email="rrb@test.com"):
    u = User(email=email, name="RRB User", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db):
    org = Organization(name="RRB Org", status="active", verified=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _make_membership(db, org_id, user_id):
    db.add(OrganizationUser(organization_id=org_id, user_id=user_id, role="owner"))
    db.commit()


def _make_category(db, name="RRBCat"):
    cat = Category(name=name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _auth(user_id):
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id})}"}


def _recurrence(frequency, interval, end_type, total_count=None, end_date=None):
    r = {"frequency": frequency, "interval": interval, "end_type": end_type}
    if total_count is not None:
        r["total_count"] = total_count
    if end_date is not None:
        r["end_date"] = str(end_date)
    return r


def _series_count(db, series_id):
    return db.query(Event).filter(Event.series_id == series_id).count()


def _make_series_direct(db, org_id, cat_id, dates, frequency="weekly"):
    """Insert an EventSeries + Event rows directly, bypassing the API."""
    series = EventSeries(
        frequency=frequency,
        interval=1,
        end_type="count",
        total_count=len(dates),
        generated_until=dates[-1],
    )
    db.add(series)
    db.flush()
    events = []
    for i, dt in enumerate(dates):
        e = Event(
            organization_id=org_id,
            category_id=cat_id,
            title=f"Event {i}",
            start_datetime=dt,
            series_id=series.id,
            occurrence_index=i,
            original_start_datetime=dt,
        )
        db.add(e)
        db.flush()
        db.add(EventCategory(event_id=e.id, category_id=cat_id, position=0))
        events.append(e)
    db.commit()
    for e in events:
        db.refresh(e)
    return series, events


# ── 1. All occurrences future — rebuild rewrites all ──────────────────────────

def test_rebuild_all_future_produces_new_dates(client, db):
    """weekly×4, all future → change to daily×4 → Jan 7, 8, 9, 10."""
    user = _make_user(db, "rrb1@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat1")

    series, events = _make_series_direct(db, org.id, cat.id,
                                         [_FUT_1, _FUT_2, _FUT_3, _FUT_4])
    first = events[0]

    resp = client.put(
        f"/events/{first.id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=4)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    assert resp.json()["series_id"] == series.id

    db.expire_all()
    rebuilt = (
        db.query(Event)
        .filter(Event.series_id == series.id)
        .order_by(Event.occurrence_index)
        .all()
    )
    assert len(rebuilt) == 4
    assert rebuilt[0].start_datetime == datetime(2099, 1, 7, 10, 0)
    assert rebuilt[1].start_datetime == datetime(2099, 1, 8, 10, 0)
    assert rebuilt[2].start_datetime == datetime(2099, 1, 9, 10, 0)
    assert rebuilt[3].start_datetime == datetime(2099, 1, 10, 10, 0)


# ── 2. All occurrences future — series row updated in place (no new series) ───

def test_rebuild_all_future_same_series_id(client, db):
    user = _make_user(db, "rrb2@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat2")

    series, events = _make_series_direct(db, org.id, cat.id, [_FUT_1, _FUT_2, _FUT_3])
    original_series_id = series.id

    resp = client.put(
        f"/events/{events[0].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=3)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    assert resp.json()["series_id"] == original_series_id

    db.expire_all()
    assert db.query(EventSeries).filter(EventSeries.id == original_series_id).first() is not None


# ── 3. Some occurrences in the past — past events untouched ───────────────────

def test_rebuild_some_past_past_events_unchanged(client, db):
    """2 past + 2 future. After recurrence change, past events are identical."""
    user = _make_user(db, "rrb3@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat3")

    series, events = _make_series_direct(
        db, org.id, cat.id, [_PAST_1, _PAST_2, _FUT_1, _FUT_2]
    )
    past_event_ids = {events[0].id, events[1].id}
    past_titles = {events[0].id: events[0].title, events[1].id: events[1].title}

    resp = client.put(
        f"/events/{events[2].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=4)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    for event_id, original_title in past_titles.items():
        e = db.query(Event).filter(Event.id == event_id).first()
        assert e is not None, f"Past event {event_id} was deleted"
        assert e.start_datetime in (_PAST_1, _PAST_2)
        assert e.title == original_title


# ── 4. Some occurrences in the past — future events rebuilt ───────────────────

def test_rebuild_some_past_future_events_regenerated(client, db):
    """2 past + 2 future. After weekly→daily, future events are Jan 7, 8."""
    user = _make_user(db, "rrb4@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat4")

    series, events = _make_series_direct(
        db, org.id, cat.id, [_PAST_1, _PAST_2, _FUT_1, _FUT_2]
    )

    resp = client.put(
        f"/events/{events[2].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=4)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    all_events = (
        db.query(Event)
        .filter(Event.series_id == series.id)
        .order_by(Event.start_datetime)
        .all()
    )
    # Still 4 total: 2 old past + 2 new daily future
    assert len(all_events) == 4

    future_events = [e for e in all_events if e.start_datetime >= datetime(2099, 1, 1)]
    assert len(future_events) == 2
    assert future_events[0].start_datetime == datetime(2099, 1, 7, 10, 0)
    assert future_events[1].start_datetime == datetime(2099, 1, 8, 10, 0)


# ── 5. All occurrences in the past — no events added or removed ───────────────

def test_rebuild_all_past_no_events_modified(client, db):
    user = _make_user(db, "rrb5@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat5")

    past_dates = [
        datetime(2026, 9, 1, 10, 0),
        datetime(2026, 9, 8, 10, 0),
        datetime(2026, 9, 15, 10, 0),
        datetime(2026, 9, 22, 10, 0),
    ]
    series, events = _make_series_direct(db, org.id, cat.id, past_dates)

    resp = client.put(
        f"/events/{events[0].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=4)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    remaining = db.query(Event).filter(Event.series_id == series.id).all()
    assert len(remaining) == 4
    starts = {e.start_datetime for e in remaining}
    assert starts == set(past_dates)


# ── 6. All past — series metadata still updated ───────────────────────────────

def test_rebuild_all_past_series_metadata_updated(client, db):
    user = _make_user(db, "rrb6@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat6")

    past_dates = [datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 8, 10, 0)]
    series, events = _make_series_direct(db, org.id, cat.id, past_dates)

    resp = client.put(
        f"/events/{events[0].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=4)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    updated = db.query(EventSeries).filter(EventSeries.id == series.id).first()
    assert updated.frequency == "daily"
    # Fix 2: total_count = past_count (2 events, all past — no new ones added)
    assert updated.total_count == 2


# ── 7. Count preservation when only frequency changes ─────────────────────────

def test_rebuild_preserves_total_count_when_count_unchanged(client, db):
    """2 past + 2 future (count=4). Changing frequency only → 2 new future events."""
    user = _make_user(db, "rrb7@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat7")

    series, events = _make_series_direct(
        db, org.id, cat.id, [_PAST_1, _PAST_2, _FUT_1, _FUT_2]
    )

    # Change frequency weekly→daily, echo same count=4
    resp = client.put(
        f"/events/{events[2].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=4)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    all_events = db.query(Event).filter(Event.series_id == series.id).all()
    # 2 past + 2 new future = 4 total
    assert len(all_events) == 4

    s = db.query(EventSeries).filter(EventSeries.id == series.id).first()
    # Fix 2: total_count = past_count + effective_count = 2 + 2 = 4 (overall series size)
    assert s.total_count == 4
    assert s.frequency == "daily"


# ── 8. Explicit count decrease subtracts past occurrences ────────────────────

def test_rebuild_explicit_count_change_generates_new_count(client, db):
    """2 past + 2 future (count=4). Changing to count=3 → 1 new future event (3-2=1)."""
    user = _make_user(db, "rrb8@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat8")

    series, events = _make_series_direct(
        db, org.id, cat.id, [_PAST_1, _PAST_2, _FUT_1, _FUT_2]
    )

    # User explicitly sends count=3 — total series size, so future_count = 3 - 2 = 1
    resp = client.put(
        f"/events/{events[2].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=3)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    future_events = (
        db.query(Event)
        .filter(
            Event.series_id == series.id,
            Event.start_datetime >= datetime(2099, 1, 1),
        )
        .all()
    )
    assert len(future_events) == 1

    s = db.query(EventSeries).filter(EventSeries.id == series.id).first()
    assert s.total_count == 3


# ── 9. Clicking a past event still works (rebuild finds first upcoming) ────────

def test_rebuild_clicking_past_event_still_rebuilds(client, db):
    """User clicked a past event to trigger recurrence change — still works."""
    user = _make_user(db, "rrb9@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat9")

    series, events = _make_series_direct(
        db, org.id, cat.id, [_PAST_1, _PAST_2, _FUT_1, _FUT_2]
    )
    past_event = events[0]  # occurrence_index=0, in the past

    resp = client.put(
        f"/events/{past_event.id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=4)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    all_events = db.query(Event).filter(Event.series_id == series.id).all()
    future_events = [e for e in all_events if e.start_datetime >= datetime(2099, 1, 1)]
    # effective_count = 4 - 2 = 2 future events
    assert len(future_events) == 2
    assert future_events[0].start_datetime == datetime(2099, 1, 7, 10, 0)


# ── 10. Field changes alongside recurrence change apply to rebuilt events ──────

def test_rebuild_field_changes_applied_to_future_events(client, db):
    """Title change + recurrence change → rebuilt events get new title."""
    user = _make_user(db, "rrb10@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat10")

    series, events = _make_series_direct(db, org.id, cat.id, [_FUT_1, _FUT_2, _FUT_3])

    resp = client.put(
        f"/events/{events[0].id}",
        json={
            "title": "New Title",
            "recurrence": _recurrence("daily", 1, "count", total_count=2),
        },
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    rebuilt = db.query(Event).filter(Event.series_id == series.id).all()
    assert all(e.title == "New Title" for e in rebuilt)
    assert len(rebuilt) == 2


# ── 11. Past event data is not changed when future events are rebuilt ──────────

def test_rebuild_past_event_data_preserved(client, db):
    """Past events keep their original title/start after a recurrence rebuild."""
    user = _make_user(db, "rrb11@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat11")

    series, events = _make_series_direct(
        db, org.id, cat.id, [_PAST_1, _PAST_2, _FUT_1]
    )
    # Remember original past data
    orig_title_0 = events[0].title
    orig_start_0 = events[0].start_datetime
    orig_title_1 = events[1].title
    orig_start_1 = events[1].start_datetime

    resp = client.put(
        f"/events/{events[2].id}",
        json={
            "title": "Future Only Title",
            "recurrence": _recurrence("daily", 1, "count", total_count=3),
        },
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    e0 = db.query(Event).filter(Event.id == events[0].id).first()
    e1 = db.query(Event).filter(Event.id == events[1].id).first()
    assert e0.title == orig_title_0
    assert e0.start_datetime == orig_start_0
    assert e1.title == orig_title_1
    assert e1.start_datetime == orig_start_1


# ── 12. Occurrence indices on rebuilt events start from past_count ─────────────

def test_rebuild_occurrence_indices_start_after_past(client, db):
    """2 past + rebuilt future events should have occurrence_index starting at 2."""
    user = _make_user(db, "rrb12@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat12")

    series, events = _make_series_direct(
        db, org.id, cat.id, [_PAST_1, _PAST_2, _FUT_1, _FUT_2]
    )

    resp = client.put(
        f"/events/{events[2].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=4)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    future_events = (
        db.query(Event)
        .filter(
            Event.series_id == series.id,
            Event.start_datetime >= datetime(2099, 1, 1),
        )
        .order_by(Event.occurrence_index)
        .all()
    )
    assert future_events[0].occurrence_index == 2
    assert future_events[1].occurrence_index == 3


# ── 13. Ordinary field-only scope=series still updates all events ──────────────

def test_ordinary_series_scope_field_update_still_works(client, db):
    """Field-only scope=series update (no recurrence) continues to work normally."""
    user = _make_user(db, "rrb13@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat13")

    series, events = _make_series_direct(db, org.id, cat.id, [_FUT_1, _FUT_2, _FUT_3])

    resp = client.put(
        f"/events/{events[0].id}",
        json={"title": "Series Wide Title"},
        params={"scope": "series"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    all_events = db.query(Event).filter(Event.series_id == series.id).all()
    assert all(e.title == "Series Wide Title" for e in all_events)
    assert len(all_events) == 3


# ── 14. Ordinary field-only scope=single still updates only one event ──────────

def test_ordinary_single_scope_field_update_still_works(client, db):
    user = _make_user(db, "rrb14@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat14")

    series, events = _make_series_direct(db, org.id, cat.id, [_FUT_1, _FUT_2, _FUT_3])
    original_titles = [e.title for e in events]

    resp = client.put(
        f"/events/{events[1].id}",
        json={"title": "Single Change"},
        params={"scope": "single"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    updated = (
        db.query(Event)
        .filter(Event.series_id == series.id)
        .order_by(Event.occurrence_index)
        .all()
    )
    assert updated[0].title == original_titles[0]
    assert updated[1].title == "Single Change"
    assert updated[2].title == original_titles[2]


# ── 15. Fix 1 — event earlier today is treated as past, not future ─────────────

def test_event_earlier_today_is_preserved_as_past(client, db):
    """An event that started earlier today must be kept (uses _local_now, not start-of-day).

    datetime(2026, 10, 11, 6, 0) is after today's midnight but before the current
    time (~15:30 Israel), so it is past under _local_now() but would be treated
    as future by the old _today_start_local() cutoff.
    """
    user = _make_user(db, "rrb15@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat15")

    # Event that started earlier today (clearly before any afternoon run)
    earlier_today = datetime(2026, 10, 11, 6, 0)

    series, events = _make_series_direct(
        db, org.id, cat.id, [earlier_today, _FUT_1, _FUT_2]
    )
    earlier_event_id = events[0].id

    resp = client.put(
        f"/events/{events[1].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=3)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    # The earlier-today event must still exist (treated as past)
    e = db.query(Event).filter(Event.id == earlier_event_id).first()
    assert e is not None, "Event from earlier today was deleted — should be treated as past"
    assert e.start_datetime == earlier_today


# ── 16. Fix 3 — validation failure before deletion keeps future events intact ──

def test_rebuild_invalid_category_leaves_future_events_intact(client, db):
    """If category validation fails the future events must NOT be deleted.

    Validation now runs before the destructive DELETE, so a 400 response
    guarantees the series is completely unchanged.
    """
    user = _make_user(db, "rrb16@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat16")

    series, events = _make_series_direct(db, org.id, cat.id, [_FUT_1, _FUT_2, _FUT_3])
    original_ids = {e.id for e in events}

    NONEXISTENT_CAT = 99999
    resp = client.put(
        f"/events/{events[0].id}",
        json={
            "category_ids": [NONEXISTENT_CAT],
            "recurrence": _recurrence("daily", 1, "count", total_count=3),
        },
        headers=_auth(user.id),
    )
    assert resp.status_code == 400

    # All original future events must still be present — no partial delete
    remaining_ids = {
        e.id for e in db.query(Event).filter(Event.series_id == series.id).all()
    }
    assert remaining_ids == original_ids


# ── 17. Fix 4 — clicking a past event in an all-past series returns 200 ────────

def test_rebuild_all_past_clicking_past_event_returns_200(client, db):
    """When all events are past and the selected event is itself past, return 200."""
    user = _make_user(db, "rrb17@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat17")

    past_dates = [datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 8, 10, 0)]
    series, events = _make_series_direct(db, org.id, cat.id, past_dates)

    resp = client.put(
        f"/events/{events[0].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=2)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    # The clicked past event is returned
    assert resp.json()["id"] == events[0].id
    assert resp.json()["series_id"] == series.id


# ── 18. Fix 4 — clicking a past event in a mixed series rebuilds correctly ─────

def test_rebuild_mixed_clicking_past_event_rebuilds_future(client, db):
    """Clicking a past event in a mixed series still triggers correct rebuild."""
    user = _make_user(db, "rrb18@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat18")

    series, events = _make_series_direct(
        db, org.id, cat.id, [_PAST_1, _PAST_2, _FUT_1, _FUT_2]
    )
    past_event = events[0]  # click a past event to trigger rebuild

    resp = client.put(
        f"/events/{past_event.id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=4)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    # Past events unchanged
    e0 = db.query(Event).filter(Event.id == events[0].id).first()
    e1 = db.query(Event).filter(Event.id == events[1].id).first()
    assert e0 is not None and e0.start_datetime == _PAST_1
    assert e1 is not None and e1.start_datetime == _PAST_2

    # Future events rebuilt: effective_count = 4 - 2 = 2, daily from _FUT_1
    future = (
        db.query(Event)
        .filter(Event.series_id == series.id, Event.start_datetime >= datetime(2099, 1, 1))
        .order_by(Event.start_datetime)
        .all()
    )
    assert len(future) == 2
    assert future[0].start_datetime == datetime(2099, 1, 7, 10, 0)
    assert future[1].start_datetime == datetime(2099, 1, 8, 10, 0)

    # Series total_count = past_count + effective_count = 2 + 2 = 4
    s = db.query(EventSeries).filter(EventSeries.id == series.id).first()
    assert s.total_count == 4


# ── 19. Explicit count increase: future_count = new_total - past_count ─────────

def test_rebuild_explicit_count_increase_correct_future_events(client, db):
    """2 past + 2 future (count=4). Increasing to count=6 → 4 new future events (6-2=4)."""
    user = _make_user(db, "rrb19@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat19")

    series, events = _make_series_direct(
        db, org.id, cat.id, [_PAST_1, _PAST_2, _FUT_1, _FUT_2]
    )

    resp = client.put(
        f"/events/{events[2].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=6)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()
    future_events = (
        db.query(Event)
        .filter(
            Event.series_id == series.id,
            Event.start_datetime >= datetime(2099, 1, 1),
        )
        .all()
    )
    assert len(future_events) == 4

    s = db.query(EventSeries).filter(EventSeries.id == series.id).first()
    assert s.total_count == 6


# ── 20. count == past_count → HTTP 400, series unchanged ──────────────────────

def test_rebuild_count_equal_to_past_count_returns_400(client, db):
    """Requesting total_count == past_count must fail with HTTP 400 before any deletion."""
    user = _make_user(db, "rrb20@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat20")

    series, events = _make_series_direct(
        db, org.id, cat.id, [_PAST_1, _PAST_2, _FUT_1]
    )
    original_ids = {e.id for e in events}

    # past_count=2, total_count=2 → 2 <= 2 → 400
    resp = client.put(
        f"/events/{events[2].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=2)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 400
    assert "past occurrences" in resp.json()["detail"]

    db.expire_all()
    remaining_ids = {
        e.id for e in db.query(Event).filter(Event.series_id == series.id).all()
    }
    assert remaining_ids == original_ids


# ── 21. count < past_count → HTTP 400, series unchanged ───────────────────────

def test_rebuild_count_less_than_past_count_returns_400(client, db):
    """Requesting total_count < past_count must fail with HTTP 400 before any deletion."""
    user = _make_user(db, "rrb21@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Cat21")

    # 3 past events + 1 future event; user requests total_count=2 < past_count=3
    series, events = _make_series_direct(
        db, org.id, cat.id,
        [datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 8, 10, 0),
         datetime(2026, 9, 15, 10, 0), _FUT_1],
    )
    original_ids = {e.id for e in events}

    resp = client.put(
        f"/events/{events[3].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=2)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 400

    db.expire_all()
    remaining_ids = {
        e.id for e in db.query(Event).filter(Event.series_id == series.id).all()
    }
    assert remaining_ids == original_ids


# ── 22. Uncommitted bulk deletes are fully undone by db.rollback() ─────────────

def test_uncommitted_deletes_are_restored_by_rollback(db):
    """db.rollback() undoes bulk DELETEs issued within the same transaction.

    This verifies the mechanism used by get_db's except/rollback/raise pattern:
    if _create_occurrences raises after _delete_event_rows has already run,
    rolling back the session restores the original events.
    """
    from app.api.events import _delete_event_rows

    org = _make_org(db)
    cat = _make_category(db, "TxnCat")

    series, events = _make_series_direct(db, org.id, cat.id, [_FUT_1, _FUT_2, _FUT_3])
    original_ids = {e.id for e in events}

    # Simulate the destructive part of a rebuild (does NOT commit)
    _delete_event_rows([e.id for e in events], db)

    # Deletes are visible within the same transaction
    mid_count = db.query(Event).filter(Event.series_id == series.id).count()
    assert mid_count == 0

    # Rollback undoes all uncommitted deletes
    db.rollback()
    db.expire_all()

    restored_ids = {e.id for e in db.query(Event).filter(Event.series_id == series.id).all()}
    assert restored_ids == original_ids
