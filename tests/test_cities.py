import pytest
from app.models.city import City


# ── Helpers ────────────────────────────────────────────────────────────────

def _seed(db, cities):
    """Insert a list of dicts into the cities table and commit."""
    for c in cities:
        db.add(City(**c))
    db.commit()


SAMPLE_CITIES = [
    {"name_en": "Haifa",          "name_he": "חיפה",           "name_ru": "Хайфа"},
    {"name_en": "Hadera",         "name_he": "חדרה",           "name_ru": "Хадера"},
    {"name_en": "Tel Aviv-Yafo",  "name_he": "תל אביב-יפו",   "name_ru": "Тель-Авив"},
    {"name_en": "Jerusalem",      "name_he": "ירושלים",        "name_ru": "Иерусалим"},
    {"name_en": "Be'er Sheva",    "name_he": "באר שבע",        "name_ru": "Беэр-Шева"},
    {"name_en": "Eilat",          "name_he": "אילת",           "name_ru": "Эйлат"},
    {"name_en": "Nazareth",       "name_he": "נצרת",           "name_ru": "Назарет"},
]


# ── No-query tests ─────────────────────────────────────────────────────────

def test_get_cities_no_query_returns_all_ordered(client, db):
    _seed(db, SAMPLE_CITIES)
    resp = client.get("/cities/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == len(SAMPLE_CITIES)
    names = [c["name_en"] for c in data]
    assert names == sorted(names)


def test_get_cities_response_fields(client, db):
    _seed(db, SAMPLE_CITIES[:1])
    data = client.get("/cities/").json()
    assert len(data) == 1
    city = data[0]
    assert set(city.keys()) >= {"id", "name_he", "name_en", "name_ru"}
    assert isinstance(city["id"], int)


def test_get_cities_empty_db(client, db):
    resp = client.get("/cities/")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Limit tests ────────────────────────────────────────────────────────────

def test_get_cities_default_limit(client, db):
    # Seed 60 cities; without explicit limit only 50 should come back
    for i in range(60):
        db.add(City(name_en=f"City{i:03d}", name_he=f"עיר{i}", name_ru=f"Город{i}"))
    db.commit()
    resp = client.get("/cities/")
    assert resp.status_code == 200
    assert len(resp.json()) == 50


def test_get_cities_custom_limit(client, db):
    _seed(db, SAMPLE_CITIES)
    resp = client.get("/cities/?limit=3")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_get_cities_limit_max_enforced(client, db):
    resp = client.get("/cities/?limit=200")
    assert resp.status_code == 422  # FastAPI rejects > 100


# ── Search by name_en ──────────────────────────────────────────────────────

def test_search_name_en_case_insensitive(client, db):
    _seed(db, SAMPLE_CITIES)
    for q in ("ha", "Ha", "HA"):
        resp = client.get(f"/cities/?q={q}")
        assert resp.status_code == 200
        names = [c["name_en"] for c in resp.json()]
        assert "Haifa" in names,  f"Haifa missing for q={q!r}"
        assert "Hadera" in names, f"Hadera missing for q={q!r}"
        assert "Jerusalem" not in names


def test_search_name_en_partial_match(client, db):
    _seed(db, SAMPLE_CITIES)
    resp = client.get("/cities/?q=Aviv")
    names = [c["name_en"] for c in resp.json()]
    assert "Tel Aviv-Yafo" in names
    assert "Haifa" not in names


def test_search_name_en_no_results(client, db):
    _seed(db, SAMPLE_CITIES)
    resp = client.get("/cities/?q=ZZZNOTEXIST")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Search by name_he ──────────────────────────────────────────────────────

def test_search_name_he(client, db):
    _seed(db, SAMPLE_CITIES)
    resp = client.get("/cities/?q=חיפ")
    assert resp.status_code == 200
    names = [c["name_en"] for c in resp.json()]
    assert "Haifa" in names


def test_search_name_he_full(client, db):
    _seed(db, SAMPLE_CITIES)
    resp = client.get("/cities/?q=ירושלים")
    names = [c["name_en"] for c in resp.json()]
    assert "Jerusalem" in names
    assert len(names) == 1


# ── Search by name_ru ──────────────────────────────────────────────────────

def test_search_name_ru(client, db):
    _seed(db, SAMPLE_CITIES)
    # SQLite ilike is ASCII-only, so test with the exact stored prefix
    resp = client.get("/cities/?q=Хайфа")
    names = [c["name_en"] for c in resp.json()]
    assert "Haifa" in names


# ── Search results are also ordered ───────────────────────────────────────

def test_search_results_ordered_by_name_en(client, db):
    _seed(db, SAMPLE_CITIES)
    resp = client.get("/cities/?q=a")   # matches several cities
    assert resp.status_code == 200
    names = [c["name_en"] for c in resp.json()]
    assert names == sorted(names)


# ── Inactive cities excluded ───────────────────────────────────────────────

def test_inactive_cities_excluded(client, db):
    db.add(City(name_en="ActiveCity",   name_he="א", name_ru="А", is_active=True))
    db.add(City(name_en="InactiveCity", name_he="ב", name_ru="Б", is_active=False))
    db.commit()
    resp = client.get("/cities/")
    names = [c["name_en"] for c in resp.json()]
    assert "ActiveCity" in names
    assert "InactiveCity" not in names


def test_inactive_cities_excluded_from_search(client, db):
    db.add(City(name_en="Phantom", name_he="פ", name_ru="Ф", is_active=False))
    db.commit()
    resp = client.get("/cities/?q=Phantom")
    assert resp.json() == []
