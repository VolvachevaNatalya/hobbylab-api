"""
Authorization tests for /review-images/ endpoints.

Ownership: only the review author or a system admin may create or delete images.
GET /review-images/review/{id} remains public.
"""
from app.core.security import create_access_token
from app.models.organization import Organization
from app.models.review import Review
from app.models.review_image import ReviewImage
from app.models.user import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, is_system_admin=False):
    u = User(email=email, name="Test", password_hash="x", is_system_admin=is_system_admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db):
    o = Organization(name="Test Org", status="active")
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_review(db, user_id, org_id, rating=5):
    r = Review(user_id=user_id, organization_id=org_id, rating=rating)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _make_image(db, review_id, url="https://example.com/img.jpg"):
    img = ReviewImage(review_id=review_id, image_url=url)
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


def _auth(user_id):
    token = create_access_token({"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


# ── GET remains public ────────────────────────────────────────────────────────

def test_get_images_by_review_is_public(client, db):
    author = _make_user(db, "author@test.com")
    org = _make_org(db)
    review = _make_review(db, author.id, org.id)
    _make_image(db, review.id)

    resp = client.get(f"/review-images/review/{review.id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_images_empty_list_for_unknown_review(client):
    resp = client.get("/review-images/review/99999")
    assert resp.status_code == 200
    assert resp.json() == []


# ── POST: unauthenticated is rejected ─────────────────────────────────────────

def test_create_image_unauthenticated(client, db):
    author = _make_user(db, "author@test.com")
    org = _make_org(db)
    review = _make_review(db, author.id, org.id)

    resp = client.post("/review-images/", json={
        "review_id": review.id,
        "image_url": "https://example.com/img.jpg",
    })
    assert resp.status_code == 401


# ── DELETE: unauthenticated is rejected ───────────────────────────────────────

def test_delete_image_unauthenticated(client, db):
    author = _make_user(db, "author@test.com")
    org = _make_org(db)
    review = _make_review(db, author.id, org.id)
    img = _make_image(db, review.id)

    resp = client.delete(f"/review-images/{img.id}")
    assert resp.status_code == 401


# ── POST: unrelated user is rejected ─────────────────────────────────────────

def test_create_image_unrelated_user_is_rejected(client, db):
    author = _make_user(db, "author@test.com")
    stranger = _make_user(db, "stranger@test.com")
    org = _make_org(db)
    review = _make_review(db, author.id, org.id)

    resp = client.post(
        "/review-images/",
        json={"review_id": review.id, "image_url": "https://example.com/img.jpg"},
        headers=_auth(stranger.id),
    )
    assert resp.status_code == 403


# ── DELETE: unrelated user is rejected ───────────────────────────────────────

def test_delete_image_unrelated_user_is_rejected(client, db):
    author = _make_user(db, "author@test.com")
    stranger = _make_user(db, "stranger@test.com")
    org = _make_org(db)
    review = _make_review(db, author.id, org.id)
    img = _make_image(db, review.id)

    resp = client.delete(f"/review-images/{img.id}", headers=_auth(stranger.id))
    assert resp.status_code == 403


# ── Review author can create and delete their own images ─────────────────────

def test_create_image_review_author_succeeds(client, db):
    author = _make_user(db, "author@test.com")
    org = _make_org(db)
    review = _make_review(db, author.id, org.id)

    resp = client.post(
        "/review-images/",
        json={"review_id": review.id, "image_url": "https://example.com/img.jpg"},
        headers=_auth(author.id),
    )
    assert resp.status_code == 200
    assert resp.json()["review_id"] == review.id


def test_delete_image_review_author_succeeds(client, db):
    author = _make_user(db, "author@test.com")
    org = _make_org(db)
    review = _make_review(db, author.id, org.id)
    img = _make_image(db, review.id)

    resp = client.delete(f"/review-images/{img.id}", headers=_auth(author.id))
    assert resp.status_code == 200


# ── System admin can create and delete any review's images ───────────────────

def test_create_image_system_admin_succeeds(client, db):
    author = _make_user(db, "author@test.com")
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    org = _make_org(db)
    review = _make_review(db, author.id, org.id)

    resp = client.post(
        "/review-images/",
        json={"review_id": review.id, "image_url": "https://example.com/img.jpg"},
        headers=_auth(sysadmin.id),
    )
    assert resp.status_code == 200


def test_delete_image_system_admin_succeeds(client, db):
    author = _make_user(db, "author@test.com")
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)
    org = _make_org(db)
    review = _make_review(db, author.id, org.id)
    img = _make_image(db, review.id)

    resp = client.delete(f"/review-images/{img.id}", headers=_auth(sysadmin.id))
    assert resp.status_code == 200


# ── 404 on missing resources ──────────────────────────────────────────────────

def test_create_image_nonexistent_review_returns_404(client, db):
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)

    resp = client.post(
        "/review-images/",
        json={"review_id": 99999, "image_url": "https://example.com/img.jpg"},
        headers=_auth(sysadmin.id),
    )
    assert resp.status_code == 404


def test_delete_nonexistent_image_returns_404(client, db):
    sysadmin = _make_user(db, "sysadmin@test.com", is_system_admin=True)

    resp = client.delete("/review-images/99999", headers=_auth(sysadmin.id))
    assert resp.status_code == 404
