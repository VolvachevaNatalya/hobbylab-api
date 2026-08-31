"""Tests for the Event age_groups feature."""
import pytest

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_user(db, email="ag_owner@test.com"):
    user = User(email=email, name="Owner", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_org(db, name="AgeGroup Org"):
    org = Organization(name=name, status="active", verified=True)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _make_membership(db, org_id, user_id):
    row = OrganizationUser(organization_id=org_id, user_id=user_id, role="owner")
    db.add(row)
    db.commit()
    return row


def _make_category(db, name="Sport"):
    cat = Category(name=name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


def _event_body(org_id, cat_id, age_groups=None, min_age=None, max_age=None):
    body = {
        "organization_id": org_id,
        "category_ids": [cat_id],
        "title": "Test Event",
        "start_datetime": "2099-12-01T10:00:00",
    }
    if age_groups is not None:
        body["age_groups"] = age_groups
    if min_age is not None:
        body["min_age"] = min_age
    if max_age is not None:
        body["max_age"] = max_age
    return body


# ── Create: age_groups field ───────────────────────────────────────────────────

def test_create_event_with_named_age_groups(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    resp = client.post("/events/",
                       json=_event_body(org.id, cat.id, age_groups=["kids", "teens"]),
                       headers=_auth(user.id))
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["age_groups"]) == {"kids", "teens"}


def test_create_event_with_each_named_group(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    for group in ["toddlers", "kids", "teens", "adults", "family"]:
        resp = client.post("/events/",
                           json=_event_body(org.id, cat.id, age_groups=[group]),
                           headers=_auth(user.id))
        assert resp.status_code == 200, f"group={group}: {resp.json()}"
        assert group in resp.json()["age_groups"]


def test_create_event_with_custom_age_group(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    resp = client.post("/events/",
                       json=_event_body(org.id, cat.id,
                                        age_groups=["custom"], min_age=3, max_age=10),
                       headers=_auth(user.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["age_groups"] == ["custom"]
    assert data["min_age"] == 3
    assert data["max_age"] == 10


def test_create_event_no_age_groups(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    resp = client.post("/events/",
                       json=_event_body(org.id, cat.id),
                       headers=_auth(user.id))
    assert resp.status_code == 200
    assert resp.json()["age_groups"] is None


def test_create_event_empty_age_groups_normalizes_to_null(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    resp = client.post("/events/",
                       json=_event_body(org.id, cat.id, age_groups=[]),
                       headers=_auth(user.id))
    assert resp.status_code == 200
    assert resp.json()["age_groups"] is None


def test_create_event_invalid_age_group_rejected(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    resp = client.post("/events/",
                       json=_event_body(org.id, cat.id, age_groups=["babies"]),
                       headers=_auth(user.id))
    assert resp.status_code == 422


def test_create_event_duplicate_age_group_rejected(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    resp = client.post("/events/",
                       json=_event_body(org.id, cat.id, age_groups=["kids", "kids"]),
                       headers=_auth(user.id))
    assert resp.status_code == 422


def test_create_event_custom_inverted_range_rejected(client, db):
    user = _make_user(db)
    org = _make_org(db)
    _make_membership(db, org.id, user.id)
    cat = _make_category(db)

    resp = client.post("/events/",
                       json=_event_body(org.id, cat.id,
                                        age_groups=["custom"], min_age=10, max_age=5),
                       headers=_auth(user.id))
    assert resp.status_code == 422


# ── Update: age_groups field ───────────────────────────────────────────────────

def _create_event(client, db, age_groups=None, min_age=None, max_age=None):
    user = _make_user(db, email="upd_owner@test.com")
    org = _make_org(db, name="Update Org")
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, name="Update Cat")
    body = _event_body(org.id, cat.id, age_groups=age_groups, min_age=min_age, max_age=max_age)
    resp = client.post("/events/", json=body, headers=_auth(user.id))
    assert resp.status_code == 200
    return resp.json()["id"], _auth(user.id)


def test_update_event_age_groups(client, db):
    event_id, headers = _create_event(client, db, age_groups=["kids"])
    resp = client.put(f"/events/{event_id}",
                      json={"age_groups": ["teens", "adults"]},
                      headers=headers)
    assert resp.status_code == 200
    assert set(resp.json()["age_groups"]) == {"teens", "adults"}


def test_update_event_clear_age_groups(client, db):
    event_id, headers = _create_event(client, db, age_groups=["kids"])
    resp = client.put(f"/events/{event_id}",
                      json={"age_groups": []},
                      headers=headers)
    assert resp.status_code == 200
    assert resp.json()["age_groups"] is None


def test_update_event_age_groups_invalid_rejected(client, db):
    event_id, headers = _create_event(client, db)
    resp = client.put(f"/events/{event_id}",
                      json={"age_groups": ["unknown"]},
                      headers=headers)
    assert resp.status_code == 422


# ── GET filter: age param ──────────────────────────────────────────────────────

def _setup_events(client, db):
    """Return (user, org, cat) pre-loaded into DB."""
    user = _make_user(db, email="filter_owner@test.com")
    org = _make_org(db, name="Filter Org")
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, name="Filter Cat")
    return user, org, cat


def test_filter_by_age_matches_named_group(client, db):
    user, org, cat = _setup_events(client, db)
    headers = _auth(user.id)
    kids_id = client.post("/events/",
                          json=_event_body(org.id, cat.id, age_groups=["kids"]),
                          headers=headers).json()["id"]
    adults_id = client.post("/events/",
                            json=_event_body(org.id, cat.id, age_groups=["adults"]),
                            headers=headers).json()["id"]

    ids = {e["id"] for e in client.get("/events/", params={"age": 8, "include_past": True}).json()}
    assert kids_id in ids
    assert adults_id not in ids


def test_filter_by_age_matches_custom_group(client, db):
    user, org, cat = _setup_events(client, db)
    headers = _auth(user.id)
    in_range_id = client.post(
        "/events/",
        json=_event_body(org.id, cat.id, age_groups=["custom"], min_age=5, max_age=15),
        headers=headers,
    ).json()["id"]
    out_range_id = client.post(
        "/events/",
        json=_event_body(org.id, cat.id, age_groups=["custom"], min_age=16, max_age=30),
        headers=headers,
    ).json()["id"]

    ids = {e["id"] for e in client.get("/events/", params={"age": 10, "include_past": True}).json()}
    assert in_range_id in ids
    assert out_range_id not in ids


def test_filter_by_age_includes_no_age_restriction(client, db):
    user, org, cat = _setup_events(client, db)
    headers = _auth(user.id)
    unrestricted_id = client.post("/events/",
                                  json=_event_body(org.id, cat.id),
                                  headers=headers).json()["id"]

    ids = {e["id"] for e in client.get("/events/", params={"age": 50, "include_past": True}).json()}
    assert unrestricted_id in ids


def test_filter_by_age_family_matches_all_ages(client, db):
    user, org, cat = _setup_events(client, db)
    headers = _auth(user.id)
    family_id = client.post("/events/",
                            json=_event_body(org.id, cat.id, age_groups=["family"]),
                            headers=headers).json()["id"]

    for age in [0, 5, 25, 80]:
        ids = {e["id"] for e in
               client.get("/events/", params={"age": age, "include_past": True}).json()}
        assert family_id in ids, f"family event should appear for age={age}"


def test_filter_by_age_no_param_returns_all(client, db):
    user, org, cat = _setup_events(client, db)
    headers = _auth(user.id)
    ids_created = {
        client.post("/events/", json=_event_body(org.id, cat.id, age_groups=g),
                    headers=headers).json()["id"]
        for g in [["kids"], ["adults"], None]
    }

    ids_returned = {e["id"] for e in
                    client.get("/events/", params={"include_past": True}).json()}
    assert ids_created.issubset(ids_returned)


def test_filter_by_age_multi_group_event(client, db):
    user, org, cat = _setup_events(client, db)
    headers = _auth(user.id)
    event_id = client.post(
        "/events/",
        json=_event_body(org.id, cat.id, age_groups=["kids", "adults"]),
        headers=headers,
    ).json()["id"]

    for age in [8, 25]:
        ids = {e["id"] for e in
               client.get("/events/", params={"age": age, "include_past": True}).json()}
        assert event_id in ids, f"multi-group event should appear for age={age}"


# ── Response serialization ────────────────────────────────────────────────────

def test_age_groups_returned_as_list_not_string(client, db):
    user = _make_user(db, email="ser_owner@test.com")
    org = _make_org(db, name="Ser Org")
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, name="Ser Cat")

    event_id = client.post(
        "/events/",
        json=_event_body(org.id, cat.id, age_groups=["toddlers", "family"]),
        headers=_auth(user.id),
    ).json()["id"]

    data = client.get(f"/events/{event_id}").json()
    assert isinstance(data["age_groups"], list)
    assert set(data["age_groups"]) == {"toddlers", "family"}


def test_age_groups_round_trip(client, db):
    user = _make_user(db, email="rt_owner@test.com")
    org = _make_org(db, name="RT Org")
    _make_membership(db, org.id, user.id)
    cat = _make_category(db, name="RT Cat")

    groups = ["toddlers", "teens"]
    event_id = client.post(
        "/events/",
        json=_event_body(org.id, cat.id, age_groups=groups),
        headers=_auth(user.id),
    ).json()["id"]

    fetched = client.get(f"/events/{event_id}").json()
    assert set(fetched["age_groups"]) == set(groups)
