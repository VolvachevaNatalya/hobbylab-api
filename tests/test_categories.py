import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_admin(db):
    u = User(email="admin@test.com", name="Admin", password_hash="x", is_system_admin=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_regular_user(db):
    u = User(email="user@test.com", name="User", password_hash="x", is_system_admin=False)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _auth(user):
    token = create_access_token({"user_id": user.id})
    return {"Authorization": f"Bearer {token}"}


# ── Content / i18n tests (mutations require admin auth) ───────────────────────

def test_create_category_without_i18n(client: TestClient, db):
    admin = _make_admin(db)
    resp = client.post("/categories/", json={"name": "Sport"}, headers=_auth(admin))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Sport"
    assert data["name_en"] is None
    assert data["name_ru"] is None
    assert data["name_he"] is None


def test_create_category_with_i18n(client: TestClient, db):
    admin = _make_admin(db)
    resp = client.post("/categories/", json={
        "name": "Sport",
        "name_en": "Sport",
        "name_ru": "Спорт",
        "name_he": "ספורט",
    }, headers=_auth(admin))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Sport"
    assert data["name_en"] == "Sport"
    assert data["name_ru"] == "Спорт"
    assert data["name_he"] == "ספורט"


def test_list_categories_includes_i18n(client: TestClient, db):
    admin = _make_admin(db)
    headers = _auth(admin)
    categories = [
        {"name": "Sport",   "name_en": "Sport",   "name_ru": "Спорт",     "name_he": "ספורט"},
        {"name": "Music",   "name_en": "Music",   "name_ru": "Музыка",    "name_he": "מוזיקה"},
        {"name": "Art",     "name_en": "Art",     "name_ru": "Искусство", "name_he": "אמנות"},
        {"name": "Theater", "name_en": "Theater", "name_ru": "Театр",     "name_he": "תיאטרון"},
        {"name": "Dances",  "name_en": "Dances",  "name_ru": "Танцы",     "name_he": "ריקודים"},
    ]
    for cat in categories:
        client.post("/categories/", json=cat, headers=headers)

    resp = client.get("/categories/")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 5

    by_name = {c["name"]: c for c in results}
    assert by_name["Sport"]["name_ru"] == "Спорт"
    assert by_name["Sport"]["name_he"] == "ספורט"
    assert by_name["Music"]["name_ru"] == "Музыка"
    assert by_name["Music"]["name_he"] == "מוזיקה"
    assert by_name["Art"]["name_ru"] == "Искусство"
    assert by_name["Art"]["name_he"] == "אמנות"
    assert by_name["Theater"]["name_ru"] == "Театр"
    assert by_name["Theater"]["name_he"] == "תיאטרון"
    assert by_name["Dances"]["name_ru"] == "Танцы"
    assert by_name["Dances"]["name_he"] == "ריקודים"


def test_update_category_i18n(client: TestClient, db):
    admin = _make_admin(db)
    headers = _auth(admin)

    create_resp = client.post("/categories/", json={"name": "Art"}, headers=headers)
    assert create_resp.status_code == 200
    cat_id = create_resp.json()["id"]

    update_resp = client.put(f"/categories/{cat_id}", json={
        "name_en": "Art",
        "name_ru": "Искусство",
        "name_he": "אמנות",
    }, headers=headers)
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["name"] == "Art"
    assert data["name_en"] == "Art"
    assert data["name_ru"] == "Искусство"
    assert data["name_he"] == "אמנות"


def test_update_category_partial_i18n(client: TestClient, db):
    admin = _make_admin(db)
    headers = _auth(admin)

    create_resp = client.post("/categories/", json={
        "name": "Music",
        "name_en": "Music",
        "name_ru": "Музыка",
        "name_he": "מוזיקה",
    }, headers=headers)
    assert create_resp.status_code == 200
    cat_id = create_resp.json()["id"]

    update_resp = client.put(f"/categories/{cat_id}", json={"name_ru": "МУЗЫКА"}, headers=headers)
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["name_en"] == "Music"
    assert data["name_ru"] == "МУЗЫКА"
    assert data["name_he"] == "מוזיקה"


def test_get_category_i18n(client: TestClient, db):
    admin = _make_admin(db)
    headers = _auth(admin)

    create_resp = client.post("/categories/", json={
        "name": "Theater",
        "name_en": "Theater",
        "name_ru": "Театр",
        "name_he": "תיאטרון",
    }, headers=headers)
    assert create_resp.status_code == 200
    cat_id = create_resp.json()["id"]

    resp = client.get(f"/categories/{cat_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name_en"] == "Theater"
    assert data["name_ru"] == "Театр"
    assert data["name_he"] == "תיאטרון"


# ── Security regression tests ─────────────────────────────────────────────────

def test_create_category_unauthenticated_is_rejected(client: TestClient):
    resp = client.post("/categories/", json={"name": "Hacked"})
    assert resp.status_code == 401


def test_update_category_unauthenticated_is_rejected(client: TestClient, db):
    admin = _make_admin(db)
    cat_id = client.post(
        "/categories/", json={"name": "X"}, headers=_auth(admin)
    ).json()["id"]

    resp = client.put(f"/categories/{cat_id}", json={"name": "Hacked"})
    assert resp.status_code == 401


def test_delete_category_unauthenticated_is_rejected(client: TestClient, db):
    admin = _make_admin(db)
    cat_id = client.post(
        "/categories/", json={"name": "X"}, headers=_auth(admin)
    ).json()["id"]

    resp = client.delete(f"/categories/{cat_id}")
    assert resp.status_code == 401


def test_create_category_non_admin_is_rejected(client: TestClient, db):
    user = _make_regular_user(db)
    resp = client.post("/categories/", json={"name": "Hacked"}, headers=_auth(user))
    assert resp.status_code == 403


def test_update_category_non_admin_is_rejected(client: TestClient, db):
    admin = _make_admin(db)
    cat_id = client.post(
        "/categories/", json={"name": "X"}, headers=_auth(admin)
    ).json()["id"]

    user = _make_regular_user(db)
    resp = client.put(f"/categories/{cat_id}", json={"name": "Hacked"}, headers=_auth(user))
    assert resp.status_code == 403


def test_delete_category_non_admin_is_rejected(client: TestClient, db):
    admin = _make_admin(db)
    cat_id = client.post(
        "/categories/", json={"name": "X"}, headers=_auth(admin)
    ).json()["id"]

    user = _make_regular_user(db)
    resp = client.delete(f"/categories/{cat_id}", headers=_auth(user))
    assert resp.status_code == 403


def test_admin_can_create_update_delete_category(client: TestClient, db):
    admin = _make_admin(db)
    headers = _auth(admin)

    create_resp = client.post("/categories/", json={"name": "Temp"}, headers=headers)
    assert create_resp.status_code == 200
    cat_id = create_resp.json()["id"]

    update_resp = client.put(f"/categories/{cat_id}", json={"name": "Updated"}, headers=headers)
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated"

    delete_resp = client.delete(f"/categories/{cat_id}", headers=headers)
    assert delete_resp.status_code == 200

    assert client.get(f"/categories/{cat_id}").status_code == 404


def test_public_list_categories_requires_no_auth(client: TestClient):
    resp = client.get("/categories/")
    assert resp.status_code == 200


def test_public_get_category_requires_no_auth(client: TestClient, db):
    admin = _make_admin(db)
    cat_id = client.post(
        "/categories/", json={"name": "Public"}, headers=_auth(admin)
    ).json()["id"]

    resp = client.get(f"/categories/{cat_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Public"
