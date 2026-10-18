"""Tests for recurring event series that contain both past and future occurrences.

All series are created via _make_series_direct (direct DB insertion, no HTTP)
so that anchor dates are unambiguous regardless of when the tests run.

Scenarios covered:
  1. Changing recurrence frequency preserves every past occurrence.
  2. Future occurrences are rebuilt from the earliest upcoming date.
  3. Changing total_count (up or down) never deletes past occurrences.
  4. Moving a past occurrence to a future date via scope=single leaves all
     other series members untouched.
"""

from datetime import datetime

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.event_series import EventSeries
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User

# ── Anchor dates — stable regardless of when the tests run ───────────────────
_PAST_1 = datetime(2026, 9, 1, 10, 0)
_PAST_2 = datetime(2026, 9, 8, 10, 0)
_PAST_3 = datetime(2026, 9, 15, 10, 0)
_FUT_1 = datetime(2099, 1, 7, 10, 0)   # Monday
_FUT_2 = datetime(2099, 1, 14, 10, 0)
_FUT_3 = datetime(2099, 1, 21, 10, 0)
_FUT_MOVE = datetime(2099, 6, 1, 10, 0)  # target for the "move past→future" test


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email):
    u = User(email=email, name="MS User", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db):
    org = Organization(name="MS Org", status="active", verified=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _make_membership(db, org_id, user_id):
    db.add(OrganizationUser(organization_id=org_id, user_id=user_id, role="owner"))
    db.commit()


def _make_category(db, name="MSCat"):
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


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 1 — Frequency change: every past occurrence survives unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def test_frequency_change_preserves_all_past_occurrences(client, db):
    """weekly→daily on a 3-past + 2-future series leaves past events untouched.

    Series: _PAST_1, _PAST_2, _PAST_3, _FUT_1, _FUT_2  (weekly, count=5)
    Action: change to daily, keep total_count=5
    Expected:
    - Each past event has the same database ID and start_datetime.
    - Past events remain in the same series.
    - Two new daily future events are created starting at _FUT_1.
    - Series row: frequency="daily", total_count=5.
    """
    user = _make_user(db, "ms1@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "MS1")

    series, events = _make_series_direct(
        db, org.id, cat.id,
        [_PAST_1, _PAST_2, _PAST_3, _FUT_1, _FUT_2],
    )
    # Record what each past event looks like before the update.
    past_snapshot = {e.id: e.start_datetime for e in events[:3]}

    resp = client.put(
        f"/events/{events[0].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=5)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    assert resp.json()["series_id"] == series.id

    db.expire_all()

    # ── Each past event must still exist with its original ID and datetime ─────
    for eid, expected_start in past_snapshot.items():
        e = db.query(Event).filter(Event.id == eid).first()
        assert e is not None, f"Past event {eid} was deleted"
        assert e.start_datetime == expected_start, (
            f"Past event {eid} start_datetime was modified: {e.start_datetime}"
        )
        assert e.series_id == series.id

    # ── Future events: exactly 2, rebuilt daily from _FUT_1 ───────────────────
    # past_count=3, total_count=5 → future_count = 5 - 3 = 2
    future_events = (
        db.query(Event)
        .filter(Event.series_id == series.id, Event.start_datetime > _PAST_3)
        .order_by(Event.start_datetime)
        .all()
    )
    assert len(future_events) == 2
    assert future_events[0].start_datetime == datetime(2099, 1, 7, 10, 0)
    assert future_events[1].start_datetime == datetime(2099, 1, 8, 10, 0)

    # ── Series metadata updated ────────────────────────────────────────────────
    s = db.query(EventSeries).filter(EventSeries.id == series.id).first()
    assert s.frequency == "daily"
    assert s.total_count == 5


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 2 — Future occurrences rebuild from the earliest upcoming date
# ═══════════════════════════════════════════════════════════════════════════════

def test_future_occurrences_rebuilt_from_first_upcoming(client, db):
    """After a frequency change, new future events anchor at the earliest upcoming date.

    Series: _PAST_1, _PAST_2, _FUT_1, _FUT_2, _FUT_3  (weekly, count=5)
    Action: change to daily, keep total_count=5
    Expected:
    - Rebuild starts at _FUT_1 (earliest occurrence >= now).
    - Three new daily events: _FUT_1, _FUT_1+1day, _FUT_1+2days.
    - Rebuilt events receive occurrence_index values starting at past_count (2).
    """
    user = _make_user(db, "ms2@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "MS2")

    series, events = _make_series_direct(
        db, org.id, cat.id,
        [_PAST_1, _PAST_2, _FUT_1, _FUT_2, _FUT_3],
    )

    resp = client.put(
        f"/events/{events[2].id}",
        json={"recurrence": _recurrence("daily", 1, "count", total_count=5)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()

    # ── Exact new dates for rebuilt future events ──────────────────────────────
    future_events = (
        db.query(Event)
        .filter(Event.series_id == series.id, Event.start_datetime >= _FUT_1)
        .order_by(Event.start_datetime)
        .all()
    )
    assert len(future_events) == 3  # past_count=2, total=5 → 3 future
    assert future_events[0].start_datetime == datetime(2099, 1, 7, 10, 0)
    assert future_events[1].start_datetime == datetime(2099, 1, 8, 10, 0)
    assert future_events[2].start_datetime == datetime(2099, 1, 9, 10, 0)

    # ── occurrence_index continues from past_count, not from 0 ─────────────────
    assert future_events[0].occurrence_index == 2
    assert future_events[1].occurrence_index == 3
    assert future_events[2].occurrence_index == 4

    # ── Past events are untouched ──────────────────────────────────────────────
    past_ids = {events[0].id, events[1].id}
    surviving_past = {
        e.id for e in db.query(Event)
        .filter(Event.series_id == series.id, Event.start_datetime < _FUT_1)
        .all()
    }
    assert surviving_past == past_ids


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 3a — Count increase: past occurrences are unaffected
# ═══════════════════════════════════════════════════════════════════════════════

def test_count_increase_does_not_affect_past_occurrences(client, db):
    """Increasing total_count generates more future events without touching past ones.

    Series: _PAST_1, _PAST_2, _FUT_1, _FUT_2  (weekly, count=4)
    Action: increase total_count to 7 (same frequency)
    Expected:
    - Both past event IDs survive with their original start_datetimes.
    - 5 new future events are created (7 - 2 = 5).
    - series total_count == 7.
    """
    user = _make_user(db, "ms3a@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "MS3a")

    series, events = _make_series_direct(
        db, org.id, cat.id,
        [_PAST_1, _PAST_2, _FUT_1, _FUT_2],
    )
    past_snapshot = {e.id: e.start_datetime for e in events[:2]}

    resp = client.put(
        f"/events/{events[2].id}",
        json={"recurrence": _recurrence("weekly", 1, "count", total_count=7)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()

    # ── Past events survive with identical IDs and datetimes ──────────────────
    for eid, expected_start in past_snapshot.items():
        e = db.query(Event).filter(Event.id == eid).first()
        assert e is not None, f"Past event {eid} was deleted"
        assert e.start_datetime == expected_start

    # ── 5 future events (7 - 2 = 5) ───────────────────────────────────────────
    future_count = (
        db.query(Event)
        .filter(Event.series_id == series.id, Event.start_datetime >= _FUT_1)
        .count()
    )
    assert future_count == 5

    s = db.query(EventSeries).filter(EventSeries.id == series.id).first()
    assert s.total_count == 7


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 3b — Count decrease: past occurrences are unaffected
# ═══════════════════════════════════════════════════════════════════════════════

def test_count_decrease_does_not_affect_past_occurrences(client, db):
    """Decreasing total_count removes future events without touching past ones.

    Series: _PAST_1, _PAST_2, _FUT_1, _FUT_2, _FUT_3  (weekly, count=5)
    Action: decrease total_count to 3 (same frequency)
    Expected:
    - Both past event IDs survive with their original start_datetimes.
    - 1 future event remains (3 - 2 = 1).
    - series total_count == 3.
    """
    user = _make_user(db, "ms3b@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "MS3b")

    series, events = _make_series_direct(
        db, org.id, cat.id,
        [_PAST_1, _PAST_2, _FUT_1, _FUT_2, _FUT_3],
    )
    past_snapshot = {e.id: e.start_datetime for e in events[:2]}

    resp = client.put(
        f"/events/{events[2].id}",
        json={"recurrence": _recurrence("weekly", 1, "count", total_count=3)},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200

    db.expire_all()

    # ── Past events survive with identical IDs and datetimes ──────────────────
    for eid, expected_start in past_snapshot.items():
        e = db.query(Event).filter(Event.id == eid).first()
        assert e is not None, f"Past event {eid} was deleted"
        assert e.start_datetime == expected_start

    # ── 1 future event (3 - 2 = 1) ────────────────────────────────────────────
    future_events = (
        db.query(Event)
        .filter(Event.series_id == series.id, Event.start_datetime >= _FUT_1)
        .all()
    )
    assert len(future_events) == 1
    assert future_events[0].start_datetime == _FUT_1

    s = db.query(EventSeries).filter(EventSeries.id == series.id).first()
    assert s.total_count == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 4 — scope=single on a past occurrence: move its date to the future
# ═══════════════════════════════════════════════════════════════════════════════

def test_scope_single_on_past_event_moves_only_that_occurrence(client, db):
    """scope=single changes only the selected past event's start_datetime.

    Series: _PAST_1, _PAST_2, _FUT_1, _FUT_2  (weekly, count=4)
    Action: PUT with scope=single and start_datetime=_FUT_MOVE on events[0]
    Expected (existing backend rules):
    - Only events[0].start_datetime changes to _FUT_MOVE.
    - events[0].series_id and occurrence_index are unchanged (still in the series).
    - events[1], events[2], events[3] are completely untouched.
    - Response: is_past=False (since _FUT_MOVE is in the far future).
    """
    user = _make_user(db, "ms4@t.com")
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "MS4")

    series, events = _make_series_direct(
        db, org.id, cat.id,
        [_PAST_1, _PAST_2, _FUT_1, _FUT_2],
    )
    past_event = events[0]

    # Snapshot the events that should NOT change.
    untouched = {
        events[1].id: events[1].start_datetime,
        events[2].id: events[2].start_datetime,
        events[3].id: events[3].start_datetime,
    }

    resp = client.put(
        f"/events/{past_event.id}",
        json={"start_datetime": _FUT_MOVE.isoformat()},
        params={"scope": "single"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()

    # ── Response reflects the update ──────────────────────────────────────────
    assert data["id"] == past_event.id
    assert data["series_id"] == series.id
    assert data["is_past"] is False
    # FastAPI serialises naive datetimes as ISO 8601; check the date portion.
    assert data["start_datetime"].startswith("2099-06-01")

    db.expire_all()

    # ── The moved event: new datetime, same series membership and index ────────
    moved = db.query(Event).filter(Event.id == past_event.id).first()
    assert moved.start_datetime == _FUT_MOVE
    assert moved.series_id == series.id
    assert moved.occurrence_index == 0  # unchanged; logical index is preserved

    # ── All other events are completely untouched ──────────────────────────────
    for eid, expected_start in untouched.items():
        e = db.query(Event).filter(Event.id == eid).first()
        assert e is not None
        assert e.start_datetime == expected_start, (
            f"Event {eid} start_datetime was unexpectedly changed"
        )
        assert e.series_id == series.id
