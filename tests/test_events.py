from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    db.refresh(row)
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


def _event_body(org_id, category_ids, **kwargs):
    body = {
        "organization_id": org_id,
        "title": "Test Event",
        "start_datetime": "2099-01-01T10:00:00",
        "category_ids": category_ids,
    }
    body.update(kwargs)
    return body


# ── CREATE — basic ────────────────────────────────────────────────────────────

def test_create_event_single_category(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Dance")

    resp = client.post("/events/", json=_event_body(org.id, [cat.id]), headers=_auth(user.id))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["categories"]) == 1
    assert data["categories"][0]["id"] == cat.id
    assert data["categories"][0]["name"] == "Dance"


def test_create_event_multiple_categories(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat1 = _make_category(db, "Dance")
    cat2 = _make_category(db, "Music")
    cat3 = _make_category(db, "Art")

    resp = client.post(
        "/events/",
        json=_event_body(org.id, [cat1.id, cat2.id, cat3.id]),
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["categories"]) == 3
    assert [c["name"] for c in data["categories"]] == ["Dance", "Music", "Art"]


def test_create_event_categories_ordered_by_position(client, db):
    """Input order is preserved regardless of category IDs."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    # Create in ascending order so the second cat has a higher ID
    cat_a = _make_category(db, "Zumba")
    cat_b = _make_category(db, "Aerobics")
    # Submit in reverse-ID order to confirm position, not ID, governs sort
    resp = client.post(
        "/events/",
        json=_event_body(org.id, [cat_b.id, cat_a.id]),
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["categories"][0]["name"] == "Aerobics"
    assert data["categories"][1]["name"] == "Zumba"


# ── CREATE — backward compatibility ───────────────────────────────────────────

def test_create_event_category_id_is_first_category(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat1 = _make_category(db, "Primary")
    cat2 = _make_category(db, "Secondary")

    resp = client.post(
        "/events/",
        json=_event_body(org.id, [cat1.id, cat2.id]),
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["category_id"] == cat1.id
    assert data["category_name"] == "Primary"


# ── CREATE — validation ───────────────────────────────────────────────────────

def test_create_event_rejects_empty_category_ids(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)

    resp = client.post("/events/", json=_event_body(org.id, []), headers=_auth(user.id))
    assert resp.status_code == 422


def test_create_event_rejects_more_than_10_categories(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)

    resp = client.post(
        "/events/",
        json=_event_body(org.id, list(range(1, 12))),
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_create_event_rejects_duplicate_category_ids(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    resp = client.post(
        "/events/",
        json=_event_body(org.id, [cat.id, cat.id]),
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_create_event_rejects_nonexistent_category(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)

    resp = client.post(
        "/events/",
        json=_event_body(org.id, [99999]),
        headers=_auth(user.id),
    )
    assert resp.status_code == 400


def test_create_event_rejects_no_category_at_all(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)

    body = {"organization_id": org.id, "title": "No Cat", "start_datetime": "2026-08-01T10:00:00"}
    resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert resp.status_code == 422


# ── CREATE — legacy category_id backward compatibility ────────────────────────

def test_create_event_with_legacy_category_id(client, db):
    """Old clients sending category_id (not category_ids) still work."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Legacy")

    body = {
        "organization_id": org.id,
        "title": "Old Format Event",
        "start_datetime": "2026-08-01T10:00:00",
        "category_id": cat.id,
    }
    resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["category_id"] == cat.id
    assert data["category_name"] == "Legacy"
    assert len(data["categories"]) == 1
    assert data["categories"][0]["id"] == cat.id


def test_create_event_legacy_category_id_invalid_rejected(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)

    body = {
        "organization_id": org.id,
        "title": "Bad Cat",
        "start_datetime": "2026-08-01T10:00:00",
        "category_id": 99999,
    }
    resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert resp.status_code == 400


def test_create_event_category_ids_wins_over_category_id(client, db):
    """When both fields are present, category_ids takes precedence."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat1 = _make_category(db, "Old")
    cat2 = _make_category(db, "New1")
    cat3 = _make_category(db, "New2")

    body = {
        "organization_id": org.id,
        "title": "Both Fields",
        "start_datetime": "2026-08-01T10:00:00",
        "category_id": cat1.id,
        "category_ids": [cat2.id, cat3.id],
    }
    resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["categories"]) == 2
    names = [c["name"] for c in data["categories"]]
    assert names == ["New1", "New2"]
    # category_id should reflect category_ids[0], not the legacy field
    assert data["category_id"] == cat2.id


# ── GET detail and list ───────────────────────────────────────────────────────

def test_get_event_includes_categories(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Yoga")

    event_id = client.post(
        "/events/", json=_event_body(org.id, [cat.id]), headers=_auth(user.id)
    ).json()["id"]

    resp = client.get(f"/events/{event_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["categories"]) == 1
    assert data["categories"][0]["name"] == "Yoga"
    assert data["category_name"] == "Yoga"


def test_list_events_includes_categories(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Swimming")

    client.post("/events/", json=_event_body(org.id, [cat.id]), headers=_auth(user.id))

    resp = client.get("/events/", params={"organization_id": org.id})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert len(data[0]["categories"]) == 1
    assert data[0]["categories"][0]["name"] == "Swimming"


# ── UPDATE ────────────────────────────────────────────────────────────────────

def test_update_event_replaces_categories(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat1 = _make_category(db, "Dance")
    cat2 = _make_category(db, "Music")

    event_id = client.post(
        "/events/", json=_event_body(org.id, [cat1.id]), headers=_auth(user.id)
    ).json()["id"]

    resp = client.put(
        f"/events/{event_id}",
        json={"category_ids": [cat2.id]},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["categories"]) == 1
    assert data["categories"][0]["name"] == "Music"
    assert data["category_id"] == cat2.id
    assert data["category_name"] == "Music"


def test_update_event_without_category_ids_keeps_categories(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat1 = _make_category(db, "Dance")
    cat2 = _make_category(db, "Music")

    event_id = client.post(
        "/events/",
        json=_event_body(org.id, [cat1.id, cat2.id]),
        headers=_auth(user.id),
    ).json()["id"]

    resp = client.put(
        f"/events/{event_id}",
        json={"title": "Updated Title"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated Title"
    assert len(data["categories"]) == 2
    assert {c["name"] for c in data["categories"]} == {"Dance", "Music"}


def test_update_event_rejects_more_than_10_categories(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    event_id = client.post(
        "/events/", json=_event_body(org.id, [cat.id]), headers=_auth(user.id)
    ).json()["id"]

    resp = client.put(
        f"/events/{event_id}",
        json={"category_ids": list(range(1, 12))},
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_update_event_rejects_nonexistent_category(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    event_id = client.post(
        "/events/", json=_event_body(org.id, [cat.id]), headers=_auth(user.id)
    ).json()["id"]

    resp = client.put(
        f"/events/{event_id}",
        json={"category_ids": [99999]},
        headers=_auth(user.id),
    )
    assert resp.status_code == 400


# ── CATEGORY FILTERING ───────────────────────────────────────────────────────

def test_filter_finds_event_by_primary_category(client, db):
    """An event appears when filtering by its first (primary) category."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    sport = _make_category(db, "Sport")
    music = _make_category(db, "Music")
    art = _make_category(db, "Art")

    client.post(
        "/events/",
        json=_event_body(org.id, [sport.id, music.id, art.id]),
        headers=_auth(user.id),
    )

    resp = client.get("/events/", params={"category_id": sport.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_filter_finds_event_by_secondary_category(client, db):
    """An event with [Sport, Music, Art] appears when filtering by Music (position 1)."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    sport = _make_category(db, "Sport")
    music = _make_category(db, "Music")
    art = _make_category(db, "Art")

    client.post(
        "/events/",
        json=_event_body(org.id, [sport.id, music.id, art.id]),
        headers=_auth(user.id),
    )

    resp = client.get("/events/", params={"category_id": music.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_filter_finds_event_by_tertiary_category(client, db):
    """An event with [Sport, Music, Art] appears when filtering by Art (position 2)."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    sport = _make_category(db, "Sport")
    music = _make_category(db, "Music")
    art = _make_category(db, "Art")

    client.post(
        "/events/",
        json=_event_body(org.id, [sport.id, music.id, art.id]),
        headers=_auth(user.id),
    )

    resp = client.get("/events/", params={"category_id": art.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_filter_excludes_event_for_unrelated_category(client, db):
    """An event tagged [Sport, Music] does not appear when filtering by Art."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    sport = _make_category(db, "Sport")
    music = _make_category(db, "Music")
    art = _make_category(db, "Art")

    client.post(
        "/events/",
        json=_event_body(org.id, [sport.id, music.id]),
        headers=_auth(user.id),
    )

    resp = client.get("/events/", params={"category_id": art.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_filter_no_duplicate_rows(client, db):
    """When both events.category_id and event_categories match, event appears exactly once."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    sport = _make_category(db, "Sport")

    # New events have category_id == sport.id (legacy col) AND a junction row for sport.id
    client.post(
        "/events/",
        json=_event_body(org.id, [sport.id]),
        headers=_auth(user.id),
    )

    resp = client.get("/events/", params={"category_id": sport.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_filter_legacy_event_without_junction_rows_is_found(client, db):
    """Old events with only events.category_id (no junction rows) still appear in filter."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Legacy Cat")

    # Insert directly, bypassing API — simulates pre-migration data
    event = Event(
        organization_id=org.id,
        category_id=cat.id,
        title="Old Event",
        start_datetime=datetime(2099, 1, 1),
    )
    db.add(event)
    db.commit()

    resp = client.get("/events/", params={"category_id": cat.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_filter_by_category_and_organization_combined(client, db):
    """category_id and organization_id filters work together correctly."""
    user = _make_user(db)
    org1 = _make_org(db)
    org2 = Organization(name="Other Org", status="active", verified=True)
    db.add(org2)
    db.commit()
    db.refresh(org2)

    _make_membership(db, org1.id, user.id)
    row2 = OrganizationUser(organization_id=org2.id, user_id=user.id, role="owner")
    db.add(row2)
    db.commit()

    sport = _make_category(db, "Sport")
    music = _make_category(db, "Music")

    client.post("/events/", json=_event_body(org1.id, [sport.id]), headers=_auth(user.id))
    client.post("/events/", json=_event_body(org2.id, [sport.id, music.id]), headers=_auth(user.id))

    # org1 events filtered by sport → 1 result
    resp = client.get("/events/", params={"organization_id": org1.id, "category_id": sport.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # org1 events filtered by music → 0 results (org1's event only has Sport)
    resp = client.get("/events/", params={"organization_id": org1.id, "category_id": music.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 0


# ── Idempotency ───────────────────────────────────────────────────────────────

def test_event_categories_pk_enforces_idempotency(client, db):
    """The composite PK rejects duplicate (event_id, category_id) inserts,
    making the backfill script idempotent via ON CONFLICT DO NOTHING."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    event_id = client.post(
        "/events/", json=_event_body(org.id, [cat.id]), headers=_auth(user.id)
    ).json()["id"]

    with pytest.raises(IntegrityError):
        db.add(EventCategory(event_id=event_id, category_id=cat.id, position=0))
        db.flush()
    db.rollback()


# ── Legacy event fallback ─────────────────────────────────────────────────────

# ── include_past filter ───────────────────────────────────────────────────────

def test_list_events_excludes_past_by_default(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Filter")

    past = Event(organization_id=org.id, category_id=cat.id, title="Past Event",
                 start_datetime=datetime(2020, 1, 1, 10, 0))
    future = Event(organization_id=org.id, category_id=cat.id, title="Future Event",
                   start_datetime=datetime(2099, 1, 1, 10, 0))
    db.add_all([past, future])
    db.commit()

    resp = client.get("/events/", params={"organization_id": org.id})
    assert resp.status_code == 200
    titles = [e["title"] for e in resp.json()]
    assert "Future Event" in titles
    assert "Past Event" not in titles


def test_list_events_include_past_shows_all(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Filter2")

    past = Event(organization_id=org.id, category_id=cat.id, title="Past Event2",
                 start_datetime=datetime(2020, 1, 1, 10, 0))
    future = Event(organization_id=org.id, category_id=cat.id, title="Future Event2",
                   start_datetime=datetime(2099, 1, 1, 10, 0))
    db.add_all([past, future])
    db.commit()

    resp = client.get("/events/", params={"organization_id": org.id, "include_past": "true"})
    assert resp.status_code == 200
    titles = [e["title"] for e in resp.json()]
    assert "Future Event2" in titles
    assert "Past Event2" in titles


# ── REMOVE RECURRENCE ─────────────────────────────────────────────────────────

def _make_recurring_series(client, db, org_id, cat_id, user_id, count=3):
    """Create a weekly recurring series with `count` occurrences and return (event_ids, series_id)."""
    body = _event_body(
        org_id,
        [cat_id],
        start_datetime="2099-06-01T10:00:00",
        recurrence={"frequency": "weekly", "interval": 1, "end_type": "count", "total_count": count},
    )
    resp = client.post("/events/", json=body, headers=_auth(user_id))
    assert resp.status_code == 200
    first = resp.json()
    series_id = first["series_id"]
    assert series_id is not None

    from app.models.event import Event as EventModel
    rows = db.query(EventModel).filter(EventModel.series_id == series_id).order_by(EventModel.occurrence_index).all()
    assert len(rows) == count
    return [r.id for r in rows], series_id


def test_remove_recurrence_keeps_target_deletes_others(client, db):
    """Removing recurrence (recurrence=null) keeps only the edited occurrence; all siblings deleted."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Dance")

    event_ids, series_id = _make_recurring_series(client, db, org.id, cat.id, user.id, count=5)
    target_id = event_ids[2]  # middle occurrence
    sibling_ids = [eid for eid in event_ids if eid != target_id]

    resp = client.put(
        f"/events/{target_id}?scope=single",
        json={"recurrence": None, "title": "Standalone Now"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["series_id"] is None
    assert data["recurrence"] is None
    assert data["title"] == "Standalone Now"

    from app.models.event import Event as EventModel
    from app.models.event_series import EventSeries

    db.expire_all()
    # Target still exists and is detached
    target = db.query(EventModel).filter(EventModel.id == target_id).first()
    assert target is not None
    assert target.series_id is None
    assert target.occurrence_index is None
    # All siblings are deleted
    assert db.query(EventModel).filter(EventModel.id.in_(sibling_ids)).count() == 0
    # EventSeries row is deleted
    assert db.query(EventSeries).filter(EventSeries.id == series_id).first() is None
    # Only 1 event visible for this org
    list_resp = client.get(f"/events/?organization_id={org.id}&include_past=true")
    assert len(list_resp.json()) == 1


def test_remove_recurrence_scope_is_ignored(client, db):
    """scope parameter has no effect when removing recurrence; result is always keep-one."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Music")

    event_ids, series_id = _make_recurring_series(client, db, org.id, cat.id, user.id, count=3)
    target_id = event_ids[0]  # first occurrence, scope=future would normally only affect from here

    # Use scope=future — should behave identically to scope=single (keep target, delete others)
    resp = client.put(
        f"/events/{target_id}?scope=future",
        json={"recurrence": None},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["series_id"] is None
    assert data["recurrence"] is None

    from app.models.event import Event as EventModel
    from app.models.event_series import EventSeries

    db.expire_all()
    # Only target survives; siblings deleted; series gone
    assert db.query(EventModel).filter(EventModel.id == target_id).first() is not None
    assert db.query(EventModel).filter(EventModel.series_id == series_id).count() == 0
    assert db.query(EventSeries).filter(EventSeries.id == series_id).first() is None
    list_resp = client.get(f"/events/?organization_id={org.id}&include_past=true")
    assert len(list_resp.json()) == 1


def test_remove_recurrence_on_standalone_is_noop(client, db):
    """PUT with recurrence=null on a standalone (non-recurring) event is a no-op for series fields."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Art")

    body = _event_body(org.id, [cat.id], start_datetime="2099-09-01T10:00:00")
    create_resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert create_resp.status_code == 200
    event_id = create_resp.json()["id"]

    resp = client.put(
        f"/events/{event_id}",
        json={"recurrence": None, "title": "Still Standalone"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["series_id"] is None
    assert data["recurrence"] is None
    assert data["title"] == "Still Standalone"


def test_legacy_event_without_junction_rows_returns_categories(client, db):
    """Events with category_id but no event_categories rows (pre-backfill) still
    return a populated categories list via the _enrich fallback."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Legacy")

    event = Event(
        organization_id=org.id,
        category_id=cat.id,
        title="Old Event",
        start_datetime=datetime(2026, 8, 1),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    resp = client.get(f"/events/{event.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["category_id"] == cat.id
    assert data["category_name"] == "Legacy"
    assert len(data["categories"]) == 1
    assert data["categories"][0]["name"] == "Legacy"


def test_series_id_filter_returns_only_that_series(client, db):
    """GET /events/?series_id=X returns only occurrences of that series."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Filter")

    event_ids_a, series_id_a = _make_recurring_series(
        client, db, org.id, cat.id, user.id, count=3
    )
    event_ids_b, series_id_b = _make_recurring_series(
        client, db, org.id, cat.id, user.id, count=2
    )

    resp = client.get(f"/events/?series_id={series_id_a}&include_past=true")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert all(e["series_id"] == series_id_a for e in data)
    returned_ids = {e["id"] for e in data}
    assert returned_ids == set(event_ids_a)


def test_change_recurrence_series_updates_schedule(client, db):
    """Changing frequency from daily to weekly via scope=series is reflected in GET /events/?series_id=X."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Regression")

    body = _event_body(
        org.id,
        [cat.id],
        start_datetime="2099-07-01T09:00:00",
        recurrence={"frequency": "daily", "interval": 1, "end_type": "count", "total_count": 3},
    )
    resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert resp.status_code == 200
    first = resp.json()
    series_id = first["series_id"]
    first_id = first["id"]

    update = client.put(
        f"/events/{first_id}?scope=series",
        json={"recurrence": {"frequency": "weekly", "interval": 1, "end_type": "count", "total_count": 3}},
        headers=_auth(user.id),
    )
    assert update.status_code == 200

    schedule = client.get(f"/events/?series_id={series_id}&include_past=true")
    assert schedule.status_code == 200
    occurrences = sorted(schedule.json(), key=lambda e: e["start_datetime"])
    assert len(occurrences) == 3

    from datetime import timedelta
    dates = [datetime.fromisoformat(e["start_datetime"]) for e in occurrences]
    for i in range(1, len(dates)):
        gap = dates[i] - dates[i - 1]
        assert gap == timedelta(weeks=1), f"Expected 7-day gap, got {gap}"


# ── STANDALONE → RECURRING conversion ────────────────────────────────────────

def test_convert_standalone_to_series_preserves_event_id(client, db):
    """Existing standalone event becomes occurrence 0; its id is preserved."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Yoga")

    create_resp = client.post(
        "/events/",
        json=_event_body(org.id, [cat.id], start_datetime="2099-03-10T09:00:00"),
        headers=_auth(user.id),
    )
    assert create_resp.status_code == 200
    original_id = create_resp.json()["id"]

    put_resp = client.put(
        f"/events/{original_id}",
        json={"recurrence": {"frequency": "daily", "interval": 1, "end_type": "count", "total_count": 3}},
        headers=_auth(user.id),
    )
    assert put_resp.status_code == 200
    data = put_resp.json()

    # The returned event is still the same row
    assert data["id"] == original_id
    assert data["occurrence_index"] == 0
    assert data["series_id"] is not None
    assert data["recurrence"] is not None
    assert data["recurrence"]["frequency"] == "daily"

    series_id = data["series_id"]

    from app.models.event import Event as EventModel
    from app.models.event_series import EventSeries

    db.expire_all()
    event0 = db.query(EventModel).filter(EventModel.id == original_id).first()
    assert event0 is not None
    assert event0.series_id == series_id
    assert event0.occurrence_index == 0
    assert event0.original_start_datetime is not None

    # Series row exists
    series = db.query(EventSeries).filter(EventSeries.id == series_id).first()
    assert series is not None
    assert series.frequency == "daily"

    # All 3 occurrences exist and are ordered correctly
    all_events = (
        db.query(EventModel)
        .filter(EventModel.series_id == series_id)
        .order_by(EventModel.occurrence_index)
        .all()
    )
    assert len(all_events) == 3
    assert all_events[0].id == original_id
    assert all_events[0].occurrence_index == 0
    assert all_events[1].occurrence_index == 1
    assert all_events[2].occurrence_index == 2

    from datetime import timedelta
    assert all_events[1].start_datetime - all_events[0].start_datetime == timedelta(days=1)
    assert all_events[2].start_datetime - all_events[1].start_datetime == timedelta(days=1)


def test_convert_standalone_with_field_edits(client, db):
    """Field edits applied during conversion propagate to all occurrences."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Pilates")

    create_resp = client.post(
        "/events/",
        json=_event_body(org.id, [cat.id], start_datetime="2099-05-01T10:00:00", title="Old Title"),
        headers=_auth(user.id),
    )
    original_id = create_resp.json()["id"]

    put_resp = client.put(
        f"/events/{original_id}",
        json={
            "title": "New Title",
            "recurrence": {"frequency": "weekly", "interval": 1, "end_type": "count", "total_count": 4},
        },
        headers=_auth(user.id),
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["title"] == "New Title"

    from app.models.event import Event as EventModel
    db.expire_all()
    series_id = put_resp.json()["series_id"]
    all_events = db.query(EventModel).filter(EventModel.series_id == series_id).all()
    assert len(all_events) == 4
    assert all(e.title == "New Title" for e in all_events)


def test_convert_standalone_scope_is_ignored(client, db):
    """scope parameter has no effect when converting a standalone event to recurring."""
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, "Boxing")

    create_resp = client.post(
        "/events/",
        json=_event_body(org.id, [cat.id], start_datetime="2099-07-15T08:00:00"),
        headers=_auth(user.id),
    )
    original_id = create_resp.json()["id"]

    # Use scope=single, which would normally block recurrence changes — should be ignored
    put_resp = client.put(
        f"/events/{original_id}?scope=single",
        json={"recurrence": {"frequency": "monthly", "interval": 1, "end_type": "count", "total_count": 2}},
        headers=_auth(user.id),
    )
    assert put_resp.status_code == 200
    data = put_resp.json()
    assert data["id"] == original_id
    assert data["series_id"] is not None
    assert data["occurrence_index"] == 0

    from app.models.event import Event as EventModel
    db.expire_all()
    count = db.query(EventModel).filter(EventModel.series_id == data["series_id"]).count()
    assert count == 2
