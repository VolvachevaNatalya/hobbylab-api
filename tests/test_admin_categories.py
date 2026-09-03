"""Tests for GET /admin/categories."""
from app.core.security import create_access_token
from app.models.category import Category
from app.models.user import User

_EXPECTED_CATEGORY_FIELDS = {"id", "name", "name_en", "name_ru", "name_he", "icon_url"}


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


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ── Access control ────────────────────────────────────────────────────────────

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


# ── Response envelope ─────────────────────────────────────────────────────────

def test_admin_categories_response_envelope(client, db):
    admin = _make_user(db, "ac_env@x.com", is_system_admin=True)
    resp = client.get("/admin/categories", headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"items", "total", "limit", "offset"}


# ── Field correctness ─────────────────────────────────────────────────────────

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


# ── Empty result ──────────────────────────────────────────────────────────────

def test_admin_categories_empty_returns_empty_list(client, db):
    admin = _make_user(db, "ac_empty@x.com", is_system_admin=True)
    resp = client.get("/admin/categories", headers=_auth(admin.id))
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


# ── Pagination defaults ───────────────────────────────────────────────────────

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


# ── Ordering ──────────────────────────────────────────────────────────────────

def test_admin_categories_ordered_by_id_ascending(client, db):
    admin = _make_user(db, "ac_ord@x.com", is_system_admin=True)
    c1 = _make_category(db, name="Ord_A")
    c2 = _make_category(db, name="Ord_B")
    c3 = _make_category(db, name="Ord_C")

    resp = client.get("/admin/categories", headers=_auth(admin.id))
    ids = [i["id"] for i in resp.json()["items"]]
    pos = {cid: ids.index(cid) for cid in [c1.id, c2.id, c3.id]}
    # Lowest id appears first
    assert pos[c1.id] < pos[c2.id] < pos[c3.id]
