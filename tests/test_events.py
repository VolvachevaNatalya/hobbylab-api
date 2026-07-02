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
        "start_datetime": "2026-08-01T10:00:00",
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
