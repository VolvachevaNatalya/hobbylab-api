"""Tests for GET /admin/events."""
from datetime import datetime

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User

_EXPECTED_EVENT_FIELDS = {
    "id", "title", "status", "start_datetime", "end_datetime",
    "created_at", "city", "city_id", "price", "is_nationwide",
    "series_id", "organization_id", "organization_name", "categories",
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
