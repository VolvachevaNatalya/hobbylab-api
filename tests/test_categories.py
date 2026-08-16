import pytest
from fastapi.testclient import TestClient


def test_create_category_without_i18n(client: TestClient):
    resp = client.post("/categories/", json={"name": "Sport"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Sport"
    assert data["name_en"] is None
    assert data["name_ru"] is None
    assert data["name_he"] is None


def test_create_category_with_i18n(client: TestClient):
    resp = client.post("/categories/", json={
        "name": "Sport",
        "name_en": "Sport",
        "name_ru": "Спорт",
        "name_he": "ספורט",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Sport"
    assert data["name_en"] == "Sport"
    assert data["name_ru"] == "Спорт"
    assert data["name_he"] == "ספורט"


def test_list_categories_includes_i18n(client: TestClient):
    categories = [
        {"name": "Sport",    "name_en": "Sport",   "name_ru": "Спорт",     "name_he": "ספורט"},
        {"name": "Music",    "name_en": "Music",   "name_ru": "Музыка",    "name_he": "מוזיקה"},
        {"name": "Art",      "name_en": "Art",     "name_ru": "Искусство", "name_he": "אמנות"},
        {"name": "Theater",  "name_en": "Theater", "name_ru": "Театр",     "name_he": "תיאטרון"},
        {"name": "Dances",   "name_en": "Dances",  "name_ru": "Танцы",     "name_he": "ריקודים"},
    ]
    for cat in categories:
        client.post("/categories/", json=cat)

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


def test_update_category_i18n(client: TestClient):
    create_resp = client.post("/categories/", json={"name": "Art"})
    assert create_resp.status_code == 200
    cat_id = create_resp.json()["id"]

    update_resp = client.put(f"/categories/{cat_id}", json={
        "name_en": "Art",
        "name_ru": "Искусство",
        "name_he": "אמנות",
    })
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["name"] == "Art"
    assert data["name_en"] == "Art"
    assert data["name_ru"] == "Искусство"
    assert data["name_he"] == "אמנות"


def test_update_category_partial_i18n(client: TestClient):
    create_resp = client.post("/categories/", json={
        "name": "Music",
        "name_en": "Music",
        "name_ru": "Музыка",
        "name_he": "מוזיקה",
    })
    assert create_resp.status_code == 200
    cat_id = create_resp.json()["id"]

    # Update only the Russian name; other fields should be unchanged.
    update_resp = client.put(f"/categories/{cat_id}", json={"name_ru": "МУЗЫКА"})
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["name_en"] == "Music"
    assert data["name_ru"] == "МУЗЫКА"
    assert data["name_he"] == "מוזיקה"


def test_get_category_i18n(client: TestClient):
    create_resp = client.post("/categories/", json={
        "name": "Theater",
        "name_en": "Theater",
        "name_ru": "Театр",
        "name_he": "תיאטרון",
    })
    assert create_resp.status_code == 200
    cat_id = create_resp.json()["id"]

    resp = client.get(f"/categories/{cat_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name_en"] == "Theater"
    assert data["name_ru"] == "Театр"
    assert data["name_he"] == "תיאטרון"
