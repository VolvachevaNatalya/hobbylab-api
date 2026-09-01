"""Tests for GET /admin/users."""
from app.core.security import create_access_token
from app.models.user import User


def _make_user(db, email, is_system_admin=False, name="Test User"):
    user = User(email=email, name=name, password_hash="x",
                is_system_admin=is_system_admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ── Access control ─────────────────────────────────────────────────────────────

def test_admin_users_returns_200_for_system_admin(client, db):
    admin = _make_user(db, "admin@example.com", is_system_admin=True)
    resp = client.get("/admin/users", headers=_auth(admin.id))
    assert resp.status_code == 200


def test_admin_users_returns_403_for_non_admin(client, db):
    user = _make_user(db, "regular@example.com", is_system_admin=False)
    resp = client.get("/admin/users", headers=_auth(user.id))
    assert resp.status_code == 403


def test_admin_users_returns_401_for_unauthenticated(client, db):
    resp = client.get("/admin/users")
    assert resp.status_code == 401


# ── Response shape ─────────────────────────────────────────────────────────────

def test_admin_users_response_shape(client, db):
    admin = _make_user(db, "admin2@example.com", is_system_admin=True)
    resp = client.get("/admin/users", headers=_auth(admin.id))
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data


def test_admin_users_item_fields(client, db):
    admin = _make_user(db, "admin3@example.com", is_system_admin=True, name="Admin Three")
    resp = client.get("/admin/users", headers=_auth(admin.id))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    item = next(i for i in items if i["email"] == "admin3@example.com")
    assert set(item.keys()) == {"id", "name", "email", "provider", "status",
                                "is_system_admin", "created_at"}
    assert item["name"] == "Admin Three"
    assert item["email"] == "admin3@example.com"
    assert item["is_system_admin"] is True


def test_admin_users_does_not_expose_password_hash(client, db):
    admin = _make_user(db, "admin4@example.com", is_system_admin=True)
    resp = client.get("/admin/users", headers=_auth(admin.id))
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert "password_hash" not in item
        assert "password" not in item


# ── Pagination ─────────────────────────────────────────────────────────────────

def test_admin_users_default_limit(client, db):
    admin = _make_user(db, "pg_admin@example.com", is_system_admin=True)
    resp = client.get("/admin/users", headers=_auth(admin.id))
    data = resp.json()
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_admin_users_pagination_limit_and_offset(client, db):
    admin = _make_user(db, "pg2_admin@example.com", is_system_admin=True)
    for i in range(5):
        _make_user(db, f"pg2_user{i}@example.com")

    resp_all = client.get("/admin/users", params={"limit": 100},
                          headers=_auth(admin.id))
    total = resp_all.json()["total"]
    assert total >= 6  # admin + 5 users

    resp_p1 = client.get("/admin/users", params={"limit": 3, "offset": 0},
                         headers=_auth(admin.id))
    resp_p2 = client.get("/admin/users", params={"limit": 3, "offset": 3},
                         headers=_auth(admin.id))

    ids_p1 = {i["id"] for i in resp_p1.json()["items"]}
    ids_p2 = {i["id"] for i in resp_p2.json()["items"]}
    assert len(ids_p1) == 3
    assert len(ids_p2) == 3
    assert ids_p1.isdisjoint(ids_p2)

    assert resp_p1.json()["total"] == total
    assert resp_p1.json()["limit"] == 3
    assert resp_p1.json()["offset"] == 0
    assert resp_p2.json()["offset"] == 3


def test_admin_users_limit_capped_at_100(client, db):
    admin = _make_user(db, "cap_admin@example.com", is_system_admin=True)
    resp = client.get("/admin/users", params={"limit": 200},
                      headers=_auth(admin.id))
    assert resp.status_code == 422


def test_admin_users_sorted_newest_first(client, db):
    admin = _make_user(db, "sort_admin@example.com", is_system_admin=True)
    u1 = _make_user(db, "sort_a@example.com")
    u2 = _make_user(db, "sort_b@example.com")
    u3 = _make_user(db, "sort_c@example.com")

    resp = client.get("/admin/users", headers=_auth(admin.id))
    ids = [i["id"] for i in resp.json()["items"]]
    # Newer users (higher id when created_at ties in SQLite) must appear before older ones
    pos = {uid: ids.index(uid) for uid in [u1.id, u2.id, u3.id]}
    assert pos[u3.id] < pos[u2.id] < pos[u1.id]
