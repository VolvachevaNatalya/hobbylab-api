import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token
from app.models.category import Category
from app.models.organization import Organization
from app.models.organization_category import OrganizationCategory
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="user@test.com"):
    user = User(email=email, name="Test User", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_org_active(db, name="Test Org"):
    """Create an already-active org (bypasses API, for filter tests)."""
    org = Organization(name=name, status="active", verified=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _make_membership(db, org_id, user_id, role="owner"):
    row = OrganizationUser(organization_id=org_id, user_id=user_id, role=role)
    db.add(row)
    db.commit()
    return row


def _make_category(db, name="Dance"):
    cat = Category(name=name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _assign_categories(db, org_id, categories):
    """Directly insert organization_categories rows (for filter test setup)."""
    for pos, cat in enumerate(categories):
        db.add(OrganizationCategory(organization_id=org_id, category_id=cat.id, position=pos))
    db.commit()


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


def _org_body(name="New Org", **kwargs):
    body = {"name": name}
    body.update(kwargs)
    return body


# ── CREATE — categories in request ───────────────────────────────────────────

def test_create_org_with_categories(client, db):
    user = _make_user(db)
    cat1 = _make_category(db, "Dance")
    cat2 = _make_category(db, "Sport")

    resp = client.post(
        "/organizations/",
        json=_org_body(category_ids=[cat1.id, cat2.id]),
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["categories"]) == 2
    names = [c["name"] for c in data["categories"]]
    assert names == ["Dance", "Sport"]


def test_create_org_without_categories_rejected(client, db):
    """category_ids is required — omitting it returns 422."""
    user = _make_user(db)

    resp = client.post("/organizations/", json=_org_body(), headers=_auth(user.id))
    assert resp.status_code == 422


def test_create_org_rejects_empty_category_ids(client, db):
    user = _make_user(db)
    resp = client.post(
        "/organizations/",
        json=_org_body(category_ids=[]),
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_create_org_rejects_more_than_10_categories(client, db):
    user = _make_user(db)
    resp = client.post(
        "/organizations/",
        json=_org_body(category_ids=list(range(1, 12))),
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_create_org_rejects_duplicate_category_ids(client, db):
    user = _make_user(db)
    cat = _make_category(db)
    resp = client.post(
        "/organizations/",
        json=_org_body(category_ids=[cat.id, cat.id]),
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_create_org_rejects_nonexistent_category(client, db):
    user = _make_user(db)
    resp = client.post(
        "/organizations/",
        json=_org_body(category_ids=[99999]),
        headers=_auth(user.id),
    )
    assert resp.status_code == 400


def test_create_org_categories_ordered_by_position(client, db):
    user = _make_user(db)
    cat1 = _make_category(db, "Zumba")
    cat2 = _make_category(db, "Aerobics")

    resp = client.post(
        "/organizations/",
        json=_org_body(category_ids=[cat2.id, cat1.id]),
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["categories"]]
    assert names == ["Aerobics", "Zumba"]


# ── UPDATE — categories ───────────────────────────────────────────────────────

def test_update_org_replaces_categories(client, db):
    user = _make_user(db)
    cat1 = _make_category(db, "Dance")
    cat2 = _make_category(db, "Music")

    org_id = client.post(
        "/organizations/",
        json=_org_body(category_ids=[cat1.id]),
        headers=_auth(user.id),
    ).json()["id"]

    resp = client.put(
        f"/organizations/{org_id}",
        json={"category_ids": [cat2.id]},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["categories"]) == 1
    assert data["categories"][0]["name"] == "Music"


def test_update_org_without_category_ids_keeps_categories(client, db):
    user = _make_user(db)
    cat1 = _make_category(db, "Dance")
    cat2 = _make_category(db, "Theater")

    org_id = client.post(
        "/organizations/",
        json=_org_body(category_ids=[cat1.id, cat2.id]),
        headers=_auth(user.id),
    ).json()["id"]

    resp = client.put(
        f"/organizations/{org_id}",
        json={"name": "Updated Name"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Name"
    assert len(data["categories"]) == 2
    assert {c["name"] for c in data["categories"]} == {"Dance", "Theater"}


def test_update_org_rejects_empty_category_ids(client, db):
    user = _make_user(db)
    cat = _make_category(db)

    org_id = client.post(
        "/organizations/",
        json=_org_body(category_ids=[cat.id]),
        headers=_auth(user.id),
    ).json()["id"]

    resp = client.put(
        f"/organizations/{org_id}",
        json={"category_ids": []},
        headers=_auth(user.id),
    )
    assert resp.status_code == 422


def test_update_org_rejects_nonexistent_category(client, db):
    user = _make_user(db)
    cat = _make_category(db)

    org_id = client.post(
        "/organizations/",
        json=_org_body(category_ids=[cat.id]),
        headers=_auth(user.id),
    ).json()["id"]

    resp = client.put(
        f"/organizations/{org_id}",
        json={"category_ids": [99999]},
        headers=_auth(user.id),
    )
    assert resp.status_code == 400


# ── GET single ────────────────────────────────────────────────────────────────

def test_get_organization_includes_categories(client, db):
    org = _make_org_active(db)
    cat = _make_category(db, "Yoga")
    _assign_categories(db, org.id, [cat])

    resp = client.get(f"/organizations/{org.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["categories"]) == 1
    assert data["categories"][0]["name"] == "Yoga"


def test_get_organization_no_categories_returns_empty_list(client, db):
    org = _make_org_active(db)

    resp = client.get(f"/organizations/{org.id}")
    assert resp.status_code == 200
    assert resp.json()["categories"] == []


# ── LIST — categories in response ────────────────────────────────────────────

def test_list_organizations_includes_categories(client, db):
    org = _make_org_active(db)
    cat = _make_category(db, "Swimming")
    _assign_categories(db, org.id, [cat])

    resp = client.get("/organizations/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert len(data[0]["categories"]) == 1
    assert data[0]["categories"][0]["name"] == "Swimming"


# ── CATEGORY FILTERING ────────────────────────────────────────────────────────

def test_filter_finds_org_by_primary_category(client, db):
    org = _make_org_active(db)
    dance = _make_category(db, "Dance")
    sport = _make_category(db, "Sport")
    _assign_categories(db, org.id, [dance, sport])

    resp = client.get("/organizations/", params={"category_id": dance.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_filter_finds_org_by_secondary_category(client, db):
    """Org with [Dance, Sport] appears when filtering by Sport (position 1)."""
    org = _make_org_active(db)
    dance = _make_category(db, "Dance")
    sport = _make_category(db, "Sport")
    _assign_categories(db, org.id, [dance, sport])

    resp = client.get("/organizations/", params={"category_id": sport.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_filter_excludes_org_for_unrelated_category(client, db):
    """Org tagged [Dance, Sport] does not appear when filtering by Theater."""
    org = _make_org_active(db)
    dance = _make_category(db, "Dance")
    sport = _make_category(db, "Sport")
    theater = _make_category(db, "Theater")
    _assign_categories(db, org.id, [dance, sport])

    resp = client.get("/organizations/", params={"category_id": theater.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_filter_org_without_categories_not_found(client, db):
    """Org with no organization_categories rows does not appear in any category filter."""
    org = _make_org_active(db)
    cat = _make_category(db, "Sport")
    # intentionally no _assign_categories call

    resp = client.get("/organizations/", params={"category_id": cat.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_filter_no_duplicate_rows(client, db):
    """Org appears exactly once in results even when tagged with the filtered category."""
    org = _make_org_active(db)
    cat = _make_category(db, "Sport")
    _assign_categories(db, org.id, [cat])

    resp = client.get("/organizations/", params={"category_id": cat.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_filter_only_returns_matching_orgs(client, db):
    """Two orgs with different categories — filter returns only the matching one."""
    org1 = _make_org_active(db, name="Dance Studio")
    org2 = _make_org_active(db, name="Gym")
    dance = _make_category(db, "Dance")
    sport = _make_category(db, "Sport")
    _assign_categories(db, org1.id, [dance])
    _assign_categories(db, org2.id, [sport])

    resp = client.get("/organizations/", params={"category_id": dance.id})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Dance Studio"


# ── Idempotency ───────────────────────────────────────────────────────────────

def test_organization_categories_pk_enforces_idempotency(client, db):
    """Composite PK rejects duplicate (org_id, category_id) inserts."""
    org = _make_org_active(db)
    cat = _make_category(db)
    _assign_categories(db, org.id, [cat])

    with pytest.raises(IntegrityError):
        db.add(OrganizationCategory(organization_id=org.id, category_id=cat.id, position=0))
        db.flush()
    db.rollback()
