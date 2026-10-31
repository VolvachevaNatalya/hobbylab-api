"""
Authorization regression tests for /promotions/ endpoints, plus a smoke test
confirming that active promotions affect organization geo-search ranking.

GET /promotions/  and  GET /promotions/{id}  remain public.
POST / PUT / DELETE require system-admin authorization.

Flutter reads promotion_type from GET /organizations/, not /promotions/ directly.
The ranking logic lives in organizations.py and is not changed by this task.
"""
from datetime import datetime, timedelta

from app.core.security import create_access_token
from app.models.category import Category
from app.models.organization import Organization
from app.models.organization_category import OrganizationCategory
from app.models.promotion import Promotion
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False):
    u = User(email=email, name="Test", password_hash="x", is_system_admin=is_system_admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, name="Org", lat=None, lng=None):
    o = Organization(
        name=name,
        status="active",
        verified=True,
        latitude=lat,
        longitude=lng,
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_promotion(db, org_id, promotion_type="top", active=True):
    now = datetime.utcnow()
    p = Promotion(
        organization_id=org_id,
        promotion_type=promotion_type,
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=30) if active else now - timedelta(hours=1),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_category(db):
    c = Category(name="Test")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _link_category(db, org_id, cat_id):
    oc = OrganizationCategory(organization_id=org_id, category_id=cat_id, position=0)
    db.add(oc)
    db.commit()


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


_CREATE_PAYLOAD = {
    "organization_id": 1,
    "promotion_type": "top",
}


# ── GET endpoints remain public ───────────────────────────────────────────────

def test_list_promotions_is_public(client, db):
    org = _make_org(db)
    _make_promotion(db, org.id)
    resp = client.get("/promotions/")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_promotion_is_public(client, db):
    org = _make_org(db)
    promo = _make_promotion(db, org.id)
    resp = client.get(f"/promotions/{promo.id}")
    assert resp.status_code == 200
    assert resp.json()["promotion_type"] == "top"


def test_get_nonexistent_promotion_returns_null(client):
    resp = client.get("/promotions/99999")
    assert resp.status_code == 200
    assert resp.json() is None


# ── POST: unauthenticated → 401, non-admin → 403 ─────────────────────────────

def test_create_promotion_unauthenticated(client, db):
    org = _make_org(db)
    resp = client.post("/promotions/", json={"organization_id": org.id, "promotion_type": "top"})
    assert resp.status_code == 401


def test_create_promotion_non_admin(client, db):
    user = _make_user(db, "user@test.com")
    org = _make_org(db)
    resp = client.post(
        "/promotions/",
        json={"organization_id": org.id, "promotion_type": "featured"},
        headers=_auth(user.id),
    )
    assert resp.status_code == 403


def test_create_promotion_system_admin(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    org = _make_org(db)
    now = datetime.utcnow()
    resp = client.post(
        "/promotions/",
        json={
            "organization_id": org.id,
            "promotion_type": "featured",
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=7)).isoformat(),
        },
        headers=_auth(admin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["promotion_type"] == "featured"
    assert resp.json()["organization_id"] == org.id


# ── PUT: unauthenticated → 401, non-admin → 403 ──────────────────────────────

def test_update_promotion_unauthenticated(client, db):
    org = _make_org(db)
    promo = _make_promotion(db, org.id)
    assert client.put(f"/promotions/{promo.id}", json={"promotion_type": "highlighted"}).status_code == 401


def test_update_promotion_non_admin(client, db):
    user = _make_user(db, "user@test.com")
    org = _make_org(db)
    promo = _make_promotion(db, org.id)
    assert client.put(
        f"/promotions/{promo.id}",
        json={"promotion_type": "highlighted"},
        headers=_auth(user.id),
    ).status_code == 403


def test_update_promotion_system_admin(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    org = _make_org(db)
    promo = _make_promotion(db, org.id, promotion_type="featured")

    resp = client.put(
        f"/promotions/{promo.id}",
        json={"promotion_type": "top"},
        headers=_auth(admin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["promotion_type"] == "top"


def test_update_nonexistent_promotion_returns_404(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    assert client.put(
        "/promotions/99999",
        json={"promotion_type": "top"},
        headers=_auth(admin.id),
    ).status_code == 404


# ── DELETE: unauthenticated → 401, non-admin → 403 ───────────────────────────

def test_delete_promotion_unauthenticated(client, db):
    org = _make_org(db)
    promo = _make_promotion(db, org.id)
    assert client.delete(f"/promotions/{promo.id}").status_code == 401


def test_delete_promotion_non_admin(client, db):
    user = _make_user(db, "user@test.com")
    org = _make_org(db)
    promo = _make_promotion(db, org.id)
    assert client.delete(f"/promotions/{promo.id}", headers=_auth(user.id)).status_code == 403


def test_delete_promotion_system_admin(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    org = _make_org(db)
    promo = _make_promotion(db, org.id)

    resp = client.delete(f"/promotions/{promo.id}", headers=_auth(admin.id))
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}
    assert client.get(f"/promotions/{promo.id}").json() is None


def test_delete_nonexistent_promotion_returns_404(client, db):
    admin = _make_user(db, "admin@test.com", is_system_admin=True)
    assert client.delete("/promotions/99999", headers=_auth(admin.id)).status_code == 404


# ── Ranking: active promotions affect geo-search order ───────────────────────
#
# The ranking logic in organizations.py joins Promotion on date range and
# orders by _promo_rank (top=3, featured=2, highlighted=1, none=0).
# This test verifies that an active "top" promotion causes its org to rank
# above an identical unpromoted org when both are within the search radius.

def test_active_promotion_ranks_org_first_in_geo_search(client, db):
    # Tel Aviv-ish coordinates; both orgs at the same point so distance is equal.
    LAT, LNG = 32.0853, 34.7818

    cat = _make_category(db)

    plain_org = _make_org(db, name="Plain Org", lat=LAT, lng=LNG)
    promo_org = _make_org(db, name="Promoted Org", lat=LAT, lng=LNG)
    _link_category(db, plain_org.id, cat.id)
    _link_category(db, promo_org.id, cat.id)

    _make_promotion(db, promo_org.id, promotion_type="top", active=True)

    resp = client.get(
        "/organizations/",
        params={"user_latitude": LAT, "user_longitude": LNG, "radius_km": 10},
    )
    assert resp.status_code == 200
    names = [o["name"] for o in resp.json()]
    assert "Promoted Org" in names
    assert "Plain Org" in names
    assert names.index("Promoted Org") < names.index("Plain Org"), (
        "Promoted org must appear before the unpromoted org in geo-search results"
    )


def test_expired_promotion_does_not_affect_ranking(client, db):
    LAT, LNG = 32.0853, 34.7818

    cat = _make_category(db)

    plain_org = _make_org(db, name="Plain Org", lat=LAT, lng=LNG)
    expired_promo_org = _make_org(db, name="Expired Promo Org", lat=LAT, lng=LNG)
    _link_category(db, plain_org.id, cat.id)
    _link_category(db, expired_promo_org.id, cat.id)

    _make_promotion(db, expired_promo_org.id, promotion_type="top", active=False)

    resp = client.get(
        "/organizations/",
        params={"user_latitude": LAT, "user_longitude": LNG, "radius_km": 10},
    )
    assert resp.status_code == 200
    # Both orgs appear; expired promotion must not push its org to the front
    data = resp.json()
    assert len(data) == 2
