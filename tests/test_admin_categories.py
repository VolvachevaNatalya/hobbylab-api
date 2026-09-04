"""Tests for GET/POST/PATCH/DELETE /admin/categories."""
from datetime import datetime

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.organization import Organization
from app.models.user import User

_EXPECTED_CATEGORY_FIELDS = {"id", "name", "name_en", "name_ru", "name_he", "icon_url"}


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False):
    u = User(email=email, name="Test", password_hash="x", is_system_admin=is_system_admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_category(db, name="Cat", name_en="Cat EN", name_ru="Кат", name_he="קטגוריה", icon_url=None):
    c = Category(name=name, name_en=name_en, name_ru=name_ru, name_he=name_he, icon_url=icon_url)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_org(db, name="Org"):
    o = Organization(name=name, status="active")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_event(db, org_id, cat_id=None, title="Event"):
    e = Event(
        organization_id=org_id,
        category_id=cat_id,
        title=title,
        start_datetime=datetime(2099, 1, 1, 10, 0, 0),
        status="active",
    )
    db.add(e)
    db.flush()
    if cat_id:
        db.add(EventCategory(event_id=e.id, category_id=cat_id, position=0))
    db.commit()
    db.refresh(e)
    return e


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/categories
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_categories_200_for_system_admin(client, db):
    admin = _make_user(db, "ac_admin@x.com", is_system_admin=True)
    resp = client.get("/admin/categories", headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_categories_403_for_normal_user(client, db):
    user = _make_user(db, "ac_user@x.com")
    resp = client.get("/admin/categories", headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_categories_401_for_unauthenticated(client, db):
    resp = client.get("/admin/categories")
    assert resp.status_code == 401


def test_admin_categories_response_envelope(client, db):
    admin = _make_user(db, "ac_env@x.com", is_system_admin=True)
    resp = client.get("/admin/categories", headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"items", "total", "limit", "offset"}


def test_admin_categories_item_fields_exact(client, db):
    admin = _make_user(db, "ac_fld@x.com", is_system_admin=True)
    _make_category(db, name="Dance", name_en="Dance", name_ru="Танцы", name_he="ריקוד")

    resp = client.get("/admin/categories", headers=_auth(admin.id))
    items = resp.json()["items"]
    item = next(i for i in items if i["name"] == "Dance")
    assert set(item.keys()) == _EXPECTED_CATEGORY_FIELDS


def test_admin_categories_multilingual_fields_preserved(client, db):
    admin = _make_user(db, "ac_i18n@x.com", is_system_admin=True)
    _make_category(db, name="Sport", name_en="Sport", name_ru="Спорт", name_he="ספורט")

    resp = client.get("/admin/categories", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["name"] == "Sport")
    assert item["name_en"] == "Sport"
    assert item["name_ru"] == "Спорт"
    assert item["name_he"] == "ספורט"


def test_admin_categories_icon_url_returned(client, db):
    admin = _make_user(db, "ac_icon@x.com", is_system_admin=True)
    _make_category(db, name="Music", icon_url="https://example.com/music.png")

    resp = client.get("/admin/categories", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["name"] == "Music")
    assert item["icon_url"] == "https://example.com/music.png"


def test_admin_categories_null_fields_returned_as_none(client, db):
    admin = _make_user(db, "ac_null@x.com", is_system_admin=True)
    _make_category(db, name="NullCat", name_en=None, name_ru=None, name_he=None, icon_url=None)

    resp = client.get("/admin/categories", headers=_auth(admin.id))
    item = next(i for i in resp.json()["items"] if i["name"] == "NullCat")
    assert item["name_en"] is None
    assert item["name_ru"] is None
    assert item["name_he"] is None
    assert item["icon_url"] is None


def test_admin_categories_empty_returns_empty_list(client, db):
    admin = _make_user(db, "ac_empty@x.com", is_system_admin=True)
    resp = client.get("/admin/categories", headers=_auth(admin.id))
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_admin_categories_default_pagination(client, db):
    admin = _make_user(db, "ac_pg@x.com", is_system_admin=True)
    resp = client.get("/admin/categories", headers=_auth(admin.id))
    data = resp.json()
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_admin_categories_limit_offset(client, db):
    admin = _make_user(db, "ac_lo@x.com", is_system_admin=True)
    for i in range(6):
        _make_category(db, name=f"LO_Cat_{i}")

    total = client.get("/admin/categories", params={"limit": 100},
                       headers=_auth(admin.id)).json()["total"]
    assert total >= 6

    p1 = client.get("/admin/categories", params={"limit": 3, "offset": 0},
                    headers=_auth(admin.id)).json()
    p2 = client.get("/admin/categories", params={"limit": 3, "offset": 3},
                    headers=_auth(admin.id)).json()

    ids_p1 = {i["id"] for i in p1["items"]}
    ids_p2 = {i["id"] for i in p2["items"]}
    assert len(ids_p1) == 3
    assert len(ids_p2) == 3
    assert ids_p1.isdisjoint(ids_p2)
    assert p1["total"] == p2["total"] == total
    assert p1["limit"] == p2["limit"] == 3
    assert p2["offset"] == 3


def test_admin_categories_limit_above_100_returns_422(client, db):
    admin = _make_user(db, "ac_cap@x.com", is_system_admin=True)
    resp = client.get("/admin/categories", params={"limit": 101},
                      headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_categories_ordered_by_id_ascending(client, db):
    admin = _make_user(db, "ac_ord@x.com", is_system_admin=True)
    c1 = _make_category(db, name="Ord_A")
    c2 = _make_category(db, name="Ord_B")
    c3 = _make_category(db, name="Ord_C")

    resp = client.get("/admin/categories", headers=_auth(admin.id))
    ids = [i["id"] for i in resp.json()["items"]]
    pos = {cid: ids.index(cid) for cid in [c1.id, c2.id, c3.id]}
    assert pos[c1.id] < pos[c2.id] < pos[c3.id]


# ══════════════════════════════════════════════════════════════════════════════
# POST /admin/categories
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_categories_create_200_for_system_admin(client, db):
    admin = _make_user(db, "cr_admin@x.com", is_system_admin=True)
    resp = client.post("/admin/categories",
                       json={"name": "NewCat"},
                       headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_categories_create_403_for_normal_user(client, db):
    user = _make_user(db, "cr_user@x.com")
    resp = client.post("/admin/categories",
                       json={"name": "Forbidden"},
                       headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_categories_create_401_for_unauthenticated(client, db):
    resp = client.post("/admin/categories", json={"name": "Anon"})
    assert resp.status_code == 401


def test_admin_categories_create_returns_full_category(client, db):
    admin = _make_user(db, "cr_full@x.com", is_system_admin=True)
    resp = client.post("/admin/categories",
                       json={"name": "FullCat"},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == _EXPECTED_CATEGORY_FIELDS
    assert isinstance(data["id"], int)
    assert data["name"] == "FullCat"


def test_admin_categories_create_multilingual_preserved(client, db):
    admin = _make_user(db, "cr_i18n@x.com", is_system_admin=True)
    resp = client.post("/admin/categories",
                       json={
                           "name": "Dance",
                           "name_en": "Dance",
                           "name_ru": "Танцы",
                           "name_he": "ריקוד",
                       },
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name_en"] == "Dance"
    assert data["name_ru"] == "Танцы"
    assert data["name_he"] == "ריקוד"


def test_admin_categories_create_icon_url_preserved(client, db):
    admin = _make_user(db, "cr_icon@x.com", is_system_admin=True)
    resp = client.post("/admin/categories",
                       json={"name": "IconCat", "icon_url": "https://example.com/icon.png"},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json()["icon_url"] == "https://example.com/icon.png"


def test_admin_categories_create_optional_fields_default_to_null(client, db):
    admin = _make_user(db, "cr_opt@x.com", is_system_admin=True)
    resp = client.post("/admin/categories",
                       json={"name": "MinimalCat"},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name_en"] is None
    assert data["name_ru"] is None
    assert data["name_he"] is None
    assert data["icon_url"] is None


def test_admin_categories_create_requires_name(client, db):
    admin = _make_user(db, "cr_req@x.com", is_system_admin=True)
    resp = client.post("/admin/categories",
                       json={"name_en": "No name field"},
                       headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_categories_create_id_not_supplied_by_client(client, db):
    admin = _make_user(db, "cr_noid@x.com", is_system_admin=True)
    resp = client.post("/admin/categories",
                       json={"name": "AutoId", "id": 99999},
                       headers=_auth(admin.id))
    # Extra fields are ignored by the schema; a category is created normally.
    assert resp.status_code == 200
    # The assigned id is auto-generated, not the client-supplied value.
    assert resp.json()["id"] != 99999


def test_admin_categories_create_persisted_to_db(client, db):
    admin = _make_user(db, "cr_db@x.com", is_system_admin=True)
    resp = client.post("/admin/categories",
                       json={"name": "PersistCat", "name_en": "Persisted"},
                       headers=_auth(admin.id))
    assert resp.status_code == 200
    cat_id = resp.json()["id"]
    row = db.query(Category).filter(Category.id == cat_id).first()
    assert row is not None
    assert row.name == "PersistCat"
    assert row.name_en == "Persisted"


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /admin/categories/{category_id}
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_categories_patch_200_for_system_admin(client, db):
    admin = _make_user(db, "pa_admin@x.com", is_system_admin=True)
    cat = _make_category(db, name="PatchMe")
    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"name_en": "Updated"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_categories_patch_403_for_normal_user(client, db):
    user = _make_user(db, "pa_user@x.com")
    cat = _make_category(db, name="PatchForbid")
    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"name_en": "Nope"},
                        headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_categories_patch_401_for_unauthenticated(client, db):
    cat = _make_category(db, name="PatchAnon")
    resp = client.patch(f"/admin/categories/{cat.id}", json={"name_en": "Nope"})
    assert resp.status_code == 401


def test_admin_categories_patch_404_for_missing_category(client, db):
    admin = _make_user(db, "pa_404@x.com", is_system_admin=True)
    resp = client.patch("/admin/categories/999999",
                        json={"name_en": "Ghost"},
                        headers=_auth(admin.id))
    assert resp.status_code == 404


def test_admin_categories_patch_partial_update_preserves_other_fields(client, db):
    admin = _make_user(db, "pa_part@x.com", is_system_admin=True)
    cat = _make_category(db, name="Orig", name_en="OrigEN", name_ru="ОригРУ",
                         name_he="מקורHE", icon_url="https://example.com/orig.png")

    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"name_en": "ChangedEN"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Orig"           # unchanged
    assert data["name_en"] == "ChangedEN"   # updated
    assert data["name_ru"] == "ОригРУ"     # unchanged
    assert data["name_he"] == "מקורHE"     # unchanged
    assert data["icon_url"] == "https://example.com/orig.png"  # unchanged


def test_admin_categories_patch_name_en_update(client, db):
    admin = _make_user(db, "pa_en@x.com", is_system_admin=True)
    cat = _make_category(db, name="ENTest", name_en="Old EN")
    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"name_en": "New EN"},
                        headers=_auth(admin.id))
    assert resp.json()["name_en"] == "New EN"


def test_admin_categories_patch_name_ru_update(client, db):
    admin = _make_user(db, "pa_ru@x.com", is_system_admin=True)
    cat = _make_category(db, name="RUTest", name_ru="Старый")
    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"name_ru": "Новый"},
                        headers=_auth(admin.id))
    assert resp.json()["name_ru"] == "Новый"


def test_admin_categories_patch_name_he_preserved_exact(client, db):
    admin = _make_user(db, "pa_he@x.com", is_system_admin=True)
    cat = _make_category(db, name="HETest", name_he="ישן")
    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"name_he": "חדש"},
                        headers=_auth(admin.id))
    assert resp.json()["name_he"] == "חדש"


def test_admin_categories_patch_icon_url_update(client, db):
    admin = _make_user(db, "pa_icon@x.com", is_system_admin=True)
    cat = _make_category(db, name="IconPatch", icon_url="https://example.com/old.png")
    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"icon_url": "https://example.com/new.png"},
                        headers=_auth(admin.id))
    assert resp.json()["icon_url"] == "https://example.com/new.png"


def test_admin_categories_patch_explicit_null_clears_nullable_field(client, db):
    admin = _make_user(db, "pa_null@x.com", is_system_admin=True)
    cat = _make_category(db, name="NullPatch", name_en="Will be cleared",
                         icon_url="https://example.com/clear.png")
    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"name_en": None, "icon_url": None},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name_en"] is None
    assert data["icon_url"] is None
    assert data["name"] == "NullPatch"  # name unchanged


def test_admin_categories_patch_id_cannot_be_changed(client, db):
    admin = _make_user(db, "pa_id@x.com", is_system_admin=True)
    cat = _make_category(db, name="IDGuard")
    original_id = cat.id
    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"id": 99999, "name_en": "Harmless"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == original_id   # id unchanged
    assert data["name_en"] == "Harmless"  # the actual update went through


def test_admin_categories_patch_null_name_returns_422(client, db):
    admin = _make_user(db, "pa_nname@x.com", is_system_admin=True)
    cat = _make_category(db, name="NameGuard")
    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"name": None},
                        headers=_auth(admin.id))
    assert resp.status_code == 422
    # Category must be unchanged in the DB
    db.refresh(cat)
    assert cat.name == "NameGuard"


def test_admin_categories_patch_returns_full_category(client, db):
    admin = _make_user(db, "pa_ret@x.com", is_system_admin=True)
    cat = _make_category(db, name="ReturnMe")
    resp = client.patch(f"/admin/categories/{cat.id}",
                        json={"name": "ReturnMeUpdated"},
                        headers=_auth(admin.id))
    assert resp.status_code == 200
    assert set(resp.json().keys()) == _EXPECTED_CATEGORY_FIELDS


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /admin/categories/{category_id}
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_categories_delete_200_for_system_admin(client, db):
    admin = _make_user(db, "del_admin@x.com", is_system_admin=True)
    cat = _make_category(db, name="DeleteMe")
    resp = client.delete(f"/admin/categories/{cat.id}", headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_categories_delete_403_for_normal_user(client, db):
    user = _make_user(db, "del_user@x.com")
    cat = _make_category(db, name="DelForbid")
    resp = client.delete(f"/admin/categories/{cat.id}", headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_categories_delete_401_for_unauthenticated(client, db):
    cat = _make_category(db, name="DelAnon")
    resp = client.delete(f"/admin/categories/{cat.id}")
    assert resp.status_code == 401


def test_admin_categories_delete_404_for_missing_category(client, db):
    admin = _make_user(db, "del_404@x.com", is_system_admin=True)
    resp = client.delete("/admin/categories/999999", headers=_auth(admin.id))
    assert resp.status_code == 404


def test_admin_categories_delete_removes_category(client, db):
    admin = _make_user(db, "del_gone@x.com", is_system_admin=True)
    cat = _make_category(db, name="GoneAfterDelete")
    cat_id = cat.id

    resp = client.delete(f"/admin/categories/{cat_id}", headers=_auth(admin.id))
    assert resp.status_code == 200

    row = db.query(Category).filter(Category.id == cat_id).first()
    assert row is None


def test_admin_categories_delete_response_message(client, db):
    admin = _make_user(db, "del_msg@x.com", is_system_admin=True)
    cat = _make_category(db, name="MsgCat")
    resp = client.delete(f"/admin/categories/{cat.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert "message" in resp.json()


def test_admin_categories_delete_409_when_used_via_event_category(client, db):
    admin = _make_user(db, "del_ec@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db, name="UsedCat")
    _make_event(db, org.id, cat_id=cat.id)

    resp = client.delete(f"/admin/categories/{cat.id}", headers=_auth(admin.id))
    assert resp.status_code == 409


def test_admin_categories_delete_409_when_used_via_events_category_id(client, db):
    """Events with only events.category_id set (no EventCategory row) also block deletion."""
    admin = _make_user(db, "del_cid@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db, name="LegacyCat")
    # Create event with category_id only — no EventCategory row
    e = Event(
        organization_id=org.id,
        category_id=cat.id,
        title="LegacyEvent",
        start_datetime=datetime(2099, 1, 1, 10, 0),
        status="active",
    )
    db.add(e)
    db.commit()

    resp = client.delete(f"/admin/categories/{cat.id}", headers=_auth(admin.id))
    assert resp.status_code == 409


def test_admin_categories_delete_events_not_deleted_on_409(client, db):
    admin = _make_user(db, "del_safe@x.com", is_system_admin=True)
    org = _make_org(db)
    cat = _make_category(db, name="SafeEvtCat")
    event = _make_event(db, org.id, cat_id=cat.id, title="MustSurvive")

    client.delete(f"/admin/categories/{cat.id}", headers=_auth(admin.id))

    row = db.query(Event).filter(Event.id == event.id).first()
    assert row is not None
    assert row.title == "MustSurvive"


def test_admin_categories_delete_unused_category_is_safe(client, db):
    """Category not referenced by any event or class can be deleted."""
    admin = _make_user(db, "del_free@x.com", is_system_admin=True)
    cat = _make_category(db, name="FreeCat")

    resp = client.delete(f"/admin/categories/{cat.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert db.query(Category).filter(Category.id == cat.id).first() is None
