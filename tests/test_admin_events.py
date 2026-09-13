"""Tests for admin event endpoints (list, create, detail, update, delete)."""
from datetime import datetime, timedelta

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.event_series import EventSeries
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User

_EXPECTED_EVENT_FIELDS = {
    "id", "title", "status", "start_datetime", "end_datetime",
    "created_at", "city", "city_id", "price", "is_nationwide",
    "series_id", "organization_id", "organization_name", "categories",
    "recurrence", "occurrence_count", "last_start_datetime",
}

_EXPECTED_CATEGORY_FIELDS = {"id", "name", "name_en", "name_ru", "name_he"}

_START = "2099-01-01T10:00:00"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False):
    u = User(email=email, name="Test", password_hash="x", is_system_admin=is_system_admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, name="Org"):
    o = Organization(name=name, status="active")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_category(db, name="Cat", name_en="Cat EN", name_ru="Кат", name_he="קטגוריה"):
    c = Category(name=name, name_en=name_en, name_ru=name_ru, name_he=name_he)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_event(db, org_id, title="Event", cat_id=None, status="active"):
    e = Event(
        organization_id=org_id,
        category_id=cat_id,
        title=title,
        start_datetime=datetime(2099, 1, 1, 10, 0, 0),
        status=status,
    )
    db.add(e)
    db.flush()
    if cat_id:
        db.add(EventCategory(event_id=e.id, category_id=cat_id, position=0))
    db.commit()
    db.refresh(e)
    return e


def _link_category(db, event_id, cat_id, position=0):
    db.add(EventCategory(event_id=event_id, category_id=cat_id, position=position))
    db.commit()


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ── Access control ────────────────────────────────────────────────────────────

def test_admin_events_200_for_system_admin(client, db):
    admin = _make_user(db, "ae_admin@x.com", is_system_admin=True)
    resp = client.get("/admin/events", headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_events_403_for_normal_user(client, db):
    user = _make_user(db, "ae_user@x.com")
    resp = client.get("/admin/events", headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_events_401_for_unauthenticated(client, db):
    resp = client.get("/admin/events")
    assert resp.status_code == 401


# ── Response envelope ─────────────────────────────────────────────────────────

def test_admin_events_response_envelope(client, db):
    admin = _make_user(db, "ae_env@x.com", is_system_admin=True)
    resp = client.get("/admin/events", headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"items", "total", "limit", "offset"}


# ── Field correctness ─────────────────────────────────────────────────────────

def test_admin_events_item_fields_exact(client, db):
    admin = _make_user(db, "ae_fld@x.com", is_system_admin=True)
    org = _make_org(db, "FieldOrg")
    _make_event(db, org.id, title="FieldEvent")

    resp = client.get("/admin/events", headers=_auth(admin.id))
    items = resp.json()["items"]
    item = next(i for i in items if i["title"] == "FieldEvent")
    assert set(item.keys()) == _EXPECTED_EVENT_FIELDS


def test_admin_events_no_sensitive_fields(client, db):
    admin = _make_user(db, "ae_safe@x.com", is_system_admin=True)
    org = _make_org(db)
    _make_event(db, org.id, title="SafeEvent")

    resp = client.get("/admin/events", headers=_auth(admin.id))
    for item in resp.json()["items"]:
        assert "description" not in item
        assert "image_url" not in item
        assert "banner_url" not in item
        assert "latitude" not in item
        assert "longitude" not in item
        assert "min_age" not in item
        assert "max_age" not in item
        assert "age_groups" not in item
        assert "capacity" not in item
        assert "address" not in item
        assert "price_comment" not in item
        assert "occurrence_index" not in item
        assert "original_start_datetime" not in item
        assert "category_id" not in item   # legacy field excluded


# ── Organization info ─────────────────────────────────────────────────────────

def test_admin_events_includes_organization_name(client, db):
    admin = _make_user(db, "ae_org@x.com", is_system_admin=True)
    org = _make_org(db, "TestOrgName")
    _make_event(db, org.id, title="OrgEvent")

    resp = client.get("/admin/events", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["title"] == "OrgEvent")
    assert item["organization_id"] == org.id
    assert item["organization_name"] == "TestOrgName"


# ── Categories ────────────────────────────────────────────────────────────────

def test_admin_events_includes_categories(client, db):
    admin = _make_user(db, "ae_cat@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db, name="Dance", name_en="Dance", name_ru="Танцы", name_he="ריקוד")
    event = _make_event(db, org.id, title="CatEvent", cat_id=cat.id)

    resp = client.get("/admin/events", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["title"] == "CatEvent")
    assert len(item["categories"]) == 1
    c = item["categories"][0]
    assert c["id"] == cat.id


def test_admin_events_category_multilingual_fields(client, db):
    admin = _make_user(db, "ae_i18n@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db, name="Sport", name_en="Sport", name_ru="Спорт", name_he="ספורט")
    _make_event(db, org.id, title="I18nEvent", cat_id=cat.id)

    resp = client.get("/admin/events", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["title"] == "I18nEvent")
    c = item["categories"][0]
    assert set(c.keys()) == _EXPECTED_CATEGORY_FIELDS
    assert c["name_en"] == "Sport"
    assert c["name_ru"] == "Спорт"
    assert c["name_he"] == "ספורט"


def test_admin_events_multiple_categories(client, db):
    admin = _make_user(db, "ae_mcat@x.com", is_system_admin=True)
    org = _make_org(db)
    cat1 = _make_category(db, name="Dance")
    cat2 = _make_category(db, name="Music")
    event = _make_event(db, org.id, title="MultiCatEvent")
    _link_category(db, event.id, cat1.id, position=0)
    _link_category(db, event.id, cat2.id, position=1)

    resp = client.get("/admin/events", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["title"] == "MultiCatEvent")
    assert len(item["categories"]) == 2
    cat_names = {c["name"] for c in item["categories"]}
    assert cat_names == {"Dance", "Music"}


def test_admin_events_no_categories_returns_empty_list(client, db):
    admin = _make_user(db, "ae_nocat@x.com", is_system_admin=True)
    org = _make_org(db)
    _make_event(db, org.id, title="NoCatEvent")

    resp = client.get("/admin/events", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["title"] == "NoCatEvent")
    assert item["categories"] == []


# ── Pagination ────────────────────────────────────────────────────────────────

def test_admin_events_default_pagination(client, db):
    admin = _make_user(db, "ae_pg@x.com", is_system_admin=True)
    resp = client.get("/admin/events", headers=_auth(admin.id))
    data = resp.json()
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_admin_events_limit_offset(client, db):
    admin = _make_user(db, "ae_lo@x.com", is_system_admin=True)
    org = _make_org(db)
    for i in range(6):
        _make_event(db, org.id, title=f"LO_Event_{i}")

    total = client.get("/admin/events", params={"limit": 100},
                       headers=_auth(admin.id)).json()["total"]
    assert total >= 6

    p1 = client.get("/admin/events", params={"limit": 3, "offset": 0},
                    headers=_auth(admin.id)).json()
    p2 = client.get("/admin/events", params={"limit": 3, "offset": 3},
                    headers=_auth(admin.id)).json()

    ids_p1 = {i["id"] for i in p1["items"]}
    ids_p2 = {i["id"] for i in p2["items"]}
    assert len(ids_p1) == 3
    assert len(ids_p2) == 3
    assert ids_p1.isdisjoint(ids_p2)
    assert p1["total"] == p2["total"] == total
    assert p1["limit"] == p2["limit"] == 3
    assert p2["offset"] == 3


def test_admin_events_limit_above_100_returns_422(client, db):
    admin = _make_user(db, "ae_cap@x.com", is_system_admin=True)
    resp = client.get("/admin/events", params={"limit": 101},
                      headers=_auth(admin.id))
    assert resp.status_code == 422


# ── Ordering ──────────────────────────────────────────────────────────────────

def test_admin_events_newest_first(client, db):
    admin = _make_user(db, "ae_ord@x.com", is_system_admin=True)
    org = _make_org(db)
    e1 = _make_event(db, org.id, title="Ord_A")
    e2 = _make_event(db, org.id, title="Ord_B")
    e3 = _make_event(db, org.id, title="Ord_C")

    resp = client.get("/admin/events", headers=_auth(admin.id))
    ids = [i["id"] for i in resp.json()["items"]]
    pos = {eid: ids.index(eid) for eid in [e1.id, e2.id, e3.id]}
    # e3 created last → appears first
    assert pos[e3.id] < pos[e2.id] < pos[e1.id]


# ── Standalone list items have null series fields ─────────────────────────────

def test_admin_events_standalone_has_null_series_fields(client, db):
    admin = _make_user(db, "ae_sa_null@x.com", is_system_admin=True)
    org = _make_org(db)
    _make_event(db, org.id, title="StandaloneNullFields")

    resp = client.get("/admin/events", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["title"] == "StandaloneNullFields")
    assert item["recurrence"] is None
    assert item["occurrence_count"] is None
    assert item["last_start_datetime"] is None


# ── Series grouping ───────────────────────────────────────────────────────────

def test_admin_events_series_grouped_as_one_row(client, db):
    """A 4-occurrence series appears as exactly one row in the list."""
    admin = _make_user(db, "ae_grp@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, _ = _make_series(db, org.id, cat.id, count=4)

    resp = client.get("/admin/events", headers=_auth(admin.id))
    series_items = [i for i in resp.json()["items"] if i["series_id"] == series.id]
    assert len(series_items) == 1


def test_admin_events_total_counts_series_once(client, db):
    """total reflects display rows: 1 standalone + 1 series = 2."""
    admin = _make_user(db, "ae_tot@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    _make_event(db, org.id, title="Standalone")
    _make_series(db, org.id, cat.id, count=10)

    resp = client.get("/admin/events", params={"limit": 100}, headers=_auth(admin.id))
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_admin_events_series_row_has_recurrence(client, db):
    """Series row includes populated recurrence info from EventSeries."""
    admin = _make_user(db, "ae_rec_info@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, _ = _make_series(db, org.id, cat.id, count=4)

    resp = client.get("/admin/events", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["series_id"] == series.id)
    rec = item["recurrence"]
    assert rec is not None
    assert rec["frequency"] == "weekly"
    assert rec["interval"] == 1
    assert rec["end_type"] == "count"
    assert rec["total_count"] == 4
    assert rec["end_date"] is None


def test_admin_events_series_row_occurrence_count(client, db):
    """occurrence_count reflects how many occurrences exist in the series."""
    admin = _make_user(db, "ae_occ@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, _ = _make_series(db, org.id, cat.id, count=6)

    resp = client.get("/admin/events", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["series_id"] == series.id)
    assert item["occurrence_count"] == 6


def test_admin_events_series_row_last_start_datetime(client, db):
    """last_start_datetime matches the latest start_datetime across all occurrences."""
    admin = _make_user(db, "ae_last@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, events = _make_series(db, org.id, cat.id, count=4)

    expected_last = max(e.start_datetime for e in events).isoformat()
    resp = client.get("/admin/events", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["series_id"] == series.id)
    assert item["last_start_datetime"] == expected_last


def test_admin_events_series_row_uses_first_occurrence(client, db):
    """The representative row for a series is the first occurrence (min id)."""
    admin = _make_user(db, "ae_first@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, events = _make_series(db, org.id, cat.id, count=4)

    min_event_id = min(e.id for e in events)
    resp = client.get("/admin/events", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["series_id"] == series.id)
    assert item["id"] == min_event_id


def test_admin_events_pagination_with_series(client, db):
    """Pagination over a mix of standalone and series gives correct totals."""
    admin = _make_user(db, "ae_pgser@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    # Create 3 standalone + 1 series (5 occurrences) = 4 display rows.
    for i in range(3):
        _make_event(db, org.id, title=f"Stand_{i}")
    _make_series(db, org.id, cat.id, count=5)

    resp = client.get("/admin/events", params={"limit": 100}, headers=_auth(admin.id))
    data = resp.json()
    assert data["total"] == 4
    assert len(data["items"]) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# POST /admin/events
# ═══════════════════════════════════════════════════════════════════════════════

_START = "2099-06-01T10:00:00"


def _event_body(org_id, cat_ids, **kwargs):
    body = {
        "organization_id": org_id,
        "title": "Test Event",
        "start_datetime": _START,
        "category_ids": cat_ids,
    }
    body.update(kwargs)
    return body


def _make_series(db, org_id, cat_id, count=4):
    """Create an EventSeries with `count` weekly occurrences directly in DB."""
    series = EventSeries(frequency="weekly", interval=1, end_type="count", total_count=count)
    db.add(series)
    db.flush()
    events = []
    for i in range(count):
        dt = datetime(2099, 6, 1, 10, 0, 0) + timedelta(weeks=i)
        e = Event(
            organization_id=org_id,
            category_id=cat_id,
            title=f"Recur {i}",
            start_datetime=dt,
            series_id=series.id,
            occurrence_index=i,
            original_start_datetime=dt,
        )
        db.add(e)
        db.flush()
        db.add(EventCategory(event_id=e.id, category_id=cat_id, position=0))
        events.append(e)
    series.generated_until = events[-1].start_datetime
    db.commit()
    for e in events:
        db.refresh(e)
    db.refresh(series)
    return series, events


# ── POST auth ─────────────────────────────────────────────────────────────────

def test_admin_create_event_401_unauthenticated(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    resp = client.post("/admin/events", json=_event_body(org.id, [cat.id]))
    assert resp.status_code == 401


def test_admin_create_event_403_normal_user(client, db):
    user = _make_user(db, "ce_user@x.com")
    org = _make_org(db)
    cat = _make_category(db)
    resp = client.post("/admin/events", json=_event_body(org.id, [cat.id]),
                       headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_create_event_200_system_admin(client, db):
    admin = _make_user(db, "ce_adm@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    resp = client.post("/admin/events", json=_event_body(org.id, [cat.id]),
                       headers=_auth(admin.id))
    assert resp.status_code == 200


# ── POST create – single event ────────────────────────────────────────────────

def test_admin_create_event_single_returns_full_response(client, db):
    admin = _make_user(db, "ce_single@x.com", is_system_admin=True)
    org = _make_org(db, "SingleOrg")
    cat = _make_category(db, "Dance")
    body = _event_body(org.id, [cat.id], description="Desc", price=50.0)
    resp = client.post("/admin/events", json=body, headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test Event"
    assert data["organization_id"] == org.id
    assert data["organization_name"] == "SingleOrg"
    assert data["series_id"] is None
    assert len(data["categories"]) == 1
    assert data["categories"][0]["name"] == "Dance"
    assert data["price"] == 50.0


def test_admin_create_event_no_org_membership_required(client, db):
    """System admin can create an event without being a member of the org."""
    admin = _make_user(db, "ce_nomem@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    # Verify admin is NOT a member
    assert db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org.id,
        OrganizationUser.user_id == admin.id,
    ).first() is None
    resp = client.post("/admin/events", json=_event_body(org.id, [cat.id]),
                       headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_create_event_nonexistent_org_returns_404(client, db):
    admin = _make_user(db, "ce_noorg@x.com", is_system_admin=True)
    cat = _make_category(db)
    resp = client.post("/admin/events",
                       json=_event_body(999999, [cat.id]),
                       headers=_auth(admin.id))
    assert resp.status_code == 404


def test_admin_create_event_missing_org_id_returns_422(client, db):
    admin = _make_user(db, "ce_noid@x.com", is_system_admin=True)
    cat = _make_category(db)
    resp = client.post("/admin/events",
                       json={"title": "No Org", "start_datetime": _START, "category_ids": [cat.id]},
                       headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_create_event_missing_categories_returns_422(client, db):
    admin = _make_user(db, "ce_nocat@x.com", is_system_admin=True)
    org = _make_org(db)
    resp = client.post("/admin/events",
                       json={"organization_id": org.id, "title": "NoCat", "start_datetime": _START},
                       headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_create_event_empty_categories_returns_422(client, db):
    admin = _make_user(db, "ce_emcat@x.com", is_system_admin=True)
    org = _make_org(db)
    resp = client.post("/admin/events",
                       json=_event_body(org.id, []),
                       headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_create_event_nonexistent_category_returns_400(client, db):
    admin = _make_user(db, "ce_badcat@x.com", is_system_admin=True)
    org = _make_org(db)
    resp = client.post("/admin/events",
                       json=_event_body(org.id, [999999]),
                       headers=_auth(admin.id))
    assert resp.status_code == 400


def test_admin_create_event_multiple_categories(client, db):
    admin = _make_user(db, "ce_mcat@x.com", is_system_admin=True)
    org = _make_org(db)
    cat1 = _make_category(db, "Dance")
    cat2 = _make_category(db, "Music")
    resp = client.post("/admin/events",
                       json=_event_body(org.id, [cat1.id, cat2.id]),
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["categories"]}
    assert names == {"Dance", "Music"}


def test_admin_create_event_no_notifications_sent(client, db):
    admin = _make_user(db, "ce_notif@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    client.post("/admin/events", json=_event_body(org.id, [cat.id]),
                headers=_auth(admin.id))
    assert db.query(Notification).count() == 0


# ── POST create – recurring event ─────────────────────────────────────────────

_RECURRENCE = {"frequency": "weekly", "interval": 1, "end_type": "count", "total_count": 4}


def test_admin_create_event_recurring_success(client, db):
    admin = _make_user(db, "ce_rec@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    body = _event_body(org.id, [cat.id], recurrence=_RECURRENCE)
    resp = client.post("/admin/events", json=body, headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["series_id"] is not None
    assert data["occurrence_index"] == 0
    assert data["recurrence"]["frequency"] == "weekly"
    assert data["recurrence"]["total_count"] == 4


def test_admin_create_event_recurring_creates_series_and_occurrences(client, db):
    admin = _make_user(db, "ce_recdb@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    body = _event_body(org.id, [cat.id], recurrence=_RECURRENCE)
    resp = client.post("/admin/events", json=body, headers=_auth(admin.id))
    series_id = resp.json()["series_id"]

    series = db.query(EventSeries).filter(EventSeries.id == series_id).first()
    assert series is not None
    assert series.frequency == "weekly"
    assert series.total_count == 4

    occurrences = db.query(Event).filter(Event.series_id == series_id).all()
    assert len(occurrences) == 4
    indices = sorted(e.occurrence_index for e in occurrences)
    assert indices == [0, 1, 2, 3]


# ═══════════════════════════════════════════════════════════════════════════════
# GET /admin/events/{event_id}
# ═══════════════════════════════════════════════════════════════════════════════

_EXPECTED_DETAIL_FIELDS = {
    "id", "title", "description", "address", "city", "city_id",
    "latitude", "longitude", "image_url", "banner_url",
    "start_datetime", "end_datetime", "min_age", "max_age", "age_groups",
    "capacity", "price", "price_comment", "status", "is_nationwide",
    "organization_id", "organization_name", "categories",
    "series_id", "occurrence_index", "original_start_datetime", "created_at",
    # EventResponse also includes these; acceptable to have them in detail
    "category_id", "recurrence", "is_past", "distance_km",
    "city_name_he", "city_name_en", "city_name_ru",
    "category_name",
}


def test_admin_get_event_401_unauthenticated(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.get(f"/admin/events/{event.id}")
    assert resp.status_code == 401


def test_admin_get_event_403_normal_user(client, db):
    user = _make_user(db, "ge_user@x.com")
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.get(f"/admin/events/{event.id}", headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_get_event_200_system_admin(client, db):
    admin = _make_user(db, "ge_adm@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.get(f"/admin/events/{event.id}", headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_get_event_full_fields_returned(client, db):
    admin = _make_user(db, "ge_fld@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.get(f"/admin/events/{event.id}", headers=_auth(admin.id))
    data = resp.json()
    required = {
        "id", "title", "description", "address", "city", "city_id",
        "latitude", "longitude", "image_url", "banner_url",
        "start_datetime", "end_datetime", "min_age", "max_age",
        "capacity", "price", "price_comment", "status", "is_nationwide",
        "organization_id", "organization_name", "categories",
        "series_id", "occurrence_index", "original_start_datetime", "created_at",
    }
    assert required.issubset(set(data.keys()))


def test_admin_get_event_categories_returned(client, db):
    admin = _make_user(db, "ge_cat@x.com", is_system_admin=True)
    org = _make_org(db)
    cat1 = _make_category(db, "Dance")
    cat2 = _make_category(db, "Music")
    event = _make_event(db, org.id, cat_id=cat1.id)
    _link_category(db, event.id, cat2.id, position=1)
    resp = client.get(f"/admin/events/{event.id}", headers=_auth(admin.id))
    names = {c["name"] for c in resp.json()["categories"]}
    assert names == {"Dance", "Music"}


def test_admin_get_event_organization_name_returned(client, db):
    admin = _make_user(db, "ge_org@x.com", is_system_admin=True)
    org = _make_org(db, "DetailOrg")
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.get(f"/admin/events/{event.id}", headers=_auth(admin.id))
    assert resp.json()["organization_name"] == "DetailOrg"


def test_admin_get_event_recurrence_returned_for_series_event(client, db):
    admin = _make_user(db, "ge_rec@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    _, events = _make_series(db, org.id, cat.id)
    resp = client.get(f"/admin/events/{events[0].id}", headers=_auth(admin.id))
    data = resp.json()
    assert data["series_id"] is not None
    assert data["recurrence"] is not None
    assert data["recurrence"]["frequency"] == "weekly"
    assert data["recurrence"]["total_count"] == 4


def test_admin_get_event_404_missing(client, db):
    admin = _make_user(db, "ge_404@x.com", is_system_admin=True)
    resp = client.get("/admin/events/999999", headers=_auth(admin.id))
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# PATCH /admin/events/{event_id}
# ═══════════════════════════════════════════════════════════════════════════════

def test_admin_patch_event_401_unauthenticated(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.patch(f"/admin/events/{event.id}", json={"title": "X"})
    assert resp.status_code == 401


def test_admin_patch_event_403_normal_user(client, db):
    user = _make_user(db, "pe_user@x.com")
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.patch(f"/admin/events/{event.id}", json={"title": "X"},
                        headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_patch_event_200_system_admin(client, db):
    admin = _make_user(db, "pe_adm@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.patch(f"/admin/events/{event.id}", json={"title": "Updated"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_patch_event_single_normal(client, db):
    admin = _make_user(db, "pe_single@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, title="Original", cat_id=cat.id)
    resp = client.patch(f"/admin/events/{event.id}", json={"title": "Patched"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["title"] == "Patched"
    db.refresh(event)
    assert event.title == "Patched"


def test_admin_patch_event_partial_preserves_other_fields(client, db):
    admin = _make_user(db, "pe_partial@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, title="Keep", cat_id=cat.id)
    # Only patch description; title must not change
    resp = client.patch(f"/admin/events/{event.id}", json={"description": "New desc"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Keep"
    assert data["description"] == "New desc"


def test_admin_patch_event_organization_id_not_changeable(client, db):
    """organization_id is not in EventUpdate; sending it is silently ignored."""
    admin = _make_user(db, "pe_orgid@x.com", is_system_admin=True)
    org1 = _make_org(db, "Org1")
    org2 = _make_org(db, "Org2")
    cat = _make_category(db)
    event = _make_event(db, org1.id, cat_id=cat.id)
    resp = client.patch(f"/admin/events/{event.id}",
                        json={"title": "Moved?", "organization_id": org2.id},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    db.refresh(event)
    assert event.organization_id == org1.id


def test_admin_patch_event_categories_replace(client, db):
    admin = _make_user(db, "pe_cat@x.com", is_system_admin=True)
    org = _make_org(db)
    cat1 = _make_category(db, "Dance")
    cat2 = _make_category(db, "Music")
    event = _make_event(db, org.id, cat_id=cat1.id)
    resp = client.patch(f"/admin/events/{event.id}", json={"category_ids": [cat2.id]},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["categories"]}
    assert names == {"Music"}


def test_admin_patch_event_empty_categories_returns_422(client, db):
    admin = _make_user(db, "pe_emcat@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.patch(f"/admin/events/{event.id}", json={"category_ids": []},
                        headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_patch_event_recurring_scope_single(client, db):
    """scope=single updates only this occurrence's fields; series_id remains intact.

    Detachment from the series only happens when recurrence=null is sent explicitly
    (the remove_recurrence path). scope=single without that is a field-only update.
    """
    admin = _make_user(db, "pe_recs@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, events = _make_series(db, org.id, cat.id, count=3)
    original_series_id = series.id

    target = events[1]
    resp = client.patch(f"/admin/events/{target.id}",
                        params={"scope": "single"},
                        json={"title": "Updated Single"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated Single"
    # series_id stays intact — scope=single only updates fields
    assert data["series_id"] == original_series_id
    # Other occurrences are unchanged
    db.expire_all()
    e0 = db.query(Event).filter(Event.id == events[0].id).first()
    assert e0.title != "Updated Single"


def test_admin_patch_event_recurring_scope_future(client, db):
    """scope=future updates this and later occurrences into a new series."""
    admin = _make_user(db, "pe_recf@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    _, events = _make_series(db, org.id, cat.id, count=4)

    target = events[2]  # occurrence_index=2
    resp = client.patch(f"/admin/events/{target.id}",
                        params={"scope": "future"},
                        json={"title": "Future Title"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200

    # Events 0,1 keep old series; events 2,3 get new series
    db.expire_all()
    e0 = db.query(Event).filter(Event.id == events[0].id).first()
    e2 = db.query(Event).filter(Event.id == target.id).first()
    assert e0.series_id != e2.series_id


def test_admin_patch_event_recurring_scope_series(client, db):
    """scope=series updates all occurrences in the series."""
    admin = _make_user(db, "pe_recser@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, events = _make_series(db, org.id, cat.id, count=3)

    resp = client.patch(f"/admin/events/{events[0].id}",
                        params={"scope": "series"},
                        json={"title": "All Updated"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200

    db.expire_all()
    for e in events:
        updated = db.query(Event).filter(Event.id == e.id).first()
        assert updated.title == "All Updated"


def test_admin_patch_event_no_notifications_sent(client, db):
    admin = _make_user(db, "pe_notif@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    client.patch(f"/admin/events/{event.id}", json={"title": "Changed"},
                 headers=_auth(admin.id))
    assert db.query(Notification).count() == 0


def test_admin_patch_event_404_missing(client, db):
    admin = _make_user(db, "pe_404@x.com", is_system_admin=True)
    resp = client.patch("/admin/events/999999", json={"title": "X"},
                        headers=_auth(admin.id))
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE /admin/events/{event_id}
# ═══════════════════════════════════════════════════════════════════════════════

def test_admin_delete_event_401_unauthenticated(client, db):
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.delete(f"/admin/events/{event.id}")
    assert resp.status_code == 401


def test_admin_delete_event_403_normal_user(client, db):
    user = _make_user(db, "de_user@x.com")
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.delete(f"/admin/events/{event.id}", headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_delete_event_200_system_admin(client, db):
    admin = _make_user(db, "de_adm@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    resp = client.delete(f"/admin/events/{event.id}", headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_delete_event_single_removes_event(client, db):
    admin = _make_user(db, "de_single@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    eid = event.id
    resp = client.delete(f"/admin/events/{eid}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert db.query(Event).filter(Event.id == eid).first() is None


def test_admin_delete_event_does_not_delete_org_or_user(client, db):
    admin = _make_user(db, "de_safeou@x.com", is_system_admin=True)
    org = _make_org(db)
    user = _make_user(db, "de_orguser@x.com")
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    client.delete(f"/admin/events/{event.id}", headers=_auth(admin.id))
    assert db.query(Organization).filter(Organization.id == org.id).first() is not None
    assert db.query(User).filter(User.id == user.id).first() is not None


def test_admin_delete_event_no_notifications_sent(client, db):
    admin = _make_user(db, "de_notif@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    event = _make_event(db, org.id, cat_id=cat.id)
    client.delete(f"/admin/events/{event.id}", headers=_auth(admin.id))
    assert db.query(Notification).count() == 0


def test_admin_delete_event_404_missing(client, db):
    admin = _make_user(db, "de_404@x.com", is_system_admin=True)
    resp = client.delete("/admin/events/999999", headers=_auth(admin.id))
    assert resp.status_code == 404


def test_admin_delete_event_recurring_scope_single(client, db):
    """scope=single on a series event deletes only that occurrence."""
    admin = _make_user(db, "de_recs@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, events = _make_series(db, org.id, cat.id, count=4)

    target_id = events[1].id
    resp = client.delete(f"/admin/events/{target_id}",
                         params={"scope": "single"},
                         headers=_auth(admin.id))
    assert resp.status_code == 200
    assert db.query(Event).filter(Event.id == target_id).first() is None
    # Other 3 occurrences remain
    remaining = db.query(Event).filter(Event.series_id == series.id).count()
    assert remaining == 3
    # Series row still exists
    assert db.query(EventSeries).filter(EventSeries.id == series.id).first() is not None


def test_admin_delete_event_recurring_scope_future(client, db):
    """scope=future deletes from the selected occurrence onward."""
    admin = _make_user(db, "de_recf@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, events = _make_series(db, org.id, cat.id, count=4)

    # Delete from index 2 onward (events[2] and events[3])
    resp = client.delete(f"/admin/events/{events[2].id}",
                         params={"scope": "future"},
                         headers=_auth(admin.id))
    assert resp.status_code == 200
    remaining_ids = {r.id for r in db.query(Event).filter(Event.series_id == series.id).all()}
    assert events[0].id in remaining_ids
    assert events[1].id in remaining_ids
    assert events[2].id not in remaining_ids
    assert events[3].id not in remaining_ids


def test_admin_delete_event_recurring_scope_series(client, db):
    """scope=series deletes all occurrences and the EventSeries row."""
    admin = _make_user(db, "de_recser@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, events = _make_series(db, org.id, cat.id, count=3)
    sid = series.id
    event_ids = [e.id for e in events]

    resp = client.delete(f"/admin/events/{events[0].id}",
                         params={"scope": "series"},
                         headers=_auth(admin.id))
    assert resp.status_code == 200
    for eid in event_ids:
        assert db.query(Event).filter(Event.id == eid).first() is None
    assert db.query(EventSeries).filter(EventSeries.id == sid).first() is None


def test_admin_delete_event_scope_future_all_gone_deletes_series(client, db):
    """scope=future from index 0 removes all occurrences; series row is cleaned up."""
    admin = _make_user(db, "de_futall@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db)
    series, events = _make_series(db, org.id, cat.id, count=2)
    sid = series.id

    resp = client.delete(f"/admin/events/{events[0].id}",
                         params={"scope": "future"},
                         headers=_auth(admin.id))
    assert resp.status_code == 200
    assert db.query(EventSeries).filter(EventSeries.id == sid).first() is None
