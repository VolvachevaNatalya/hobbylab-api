"""
Regression tests for P3 security findings:

P3-1: EventUpdate.status accepts arbitrary strings
P3-2: GET /notifications/ has no pagination
P3-3: GET /events/ returns unbounded list
P3-4: Standalone review image endpoint has no per-review count limit
"""
import pytest
from datetime import datetime, timedelta

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.review import Review
from app.models.review_image import ReviewImage
from app.models.user import User


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_user(db, email, is_admin=False):
    u = User(
        email=email,
        name="Test",
        password_hash=None,
        status="active",
        is_system_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_category(db, name="Cat"):
    c = Category(name=name, name_en=name, name_ru=name, name_he=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_org(db, name="Org"):
    o = Organization(name=name, status="active", verified=True)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _make_owner(db, org_id, user_id):
    m = OrganizationUser(organization_id=org_id, user_id=user_id, role="owner")
    db.add(m)
    db.commit()


def _make_event(db, org_id, title="Event", days_ahead=1):
    start = datetime.utcnow() + timedelta(days=days_ahead)
    e = Event(
        organization_id=org_id,
        title=title,
        start_datetime=start,
        status="active",
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def _make_review(db, user_id, org_id):
    r = Review(user_id=user_id, organization_id=org_id, rating=5)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _make_image(db, review_id, n=0):
    img = ReviewImage(review_id=review_id, image_url=f"https://example.com/{n}.jpg")
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


def _make_notification(db, user_id, n=0):
    notif = Notification(
        user_id=user_id,
        type="general",
        title=f"Notification {n}",
        message=f"Message {n}",
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


def _auth(user_id):
    return {"Authorization": f"Bearer {create_access_token({'user_id': user_id, 'tv': 0})}"}


# ═══════════════════════════════════════════════════════════════════════════════
# P3-1: EventUpdate.status validator
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventUpdateStatusValidator:
    """
    Regression: EventUpdate.status accepted any string.
    After the fix, only 'active' and 'cancelled' are valid; arbitrary strings
    must be rejected with HTTP 422.
    """

    def test_arbitrary_status_rejected_on_mobile_endpoint(self, client, db):
        cat = _make_category(db)
        owner = _make_user(db, "ev_status_owner@test.com")
        org = _make_org(db)
        _make_owner(db, org.id, owner.id)
        event = _make_event(db, org.id)

        resp = client.put(
            f"/events/{event.id}",
            json={"status": "deleted", "category_ids": [cat.id]},
            headers=_auth(owner.id),
        )

        assert resp.status_code == 422, (
            f"Arbitrary status 'deleted' was accepted: HTTP {resp.status_code}"
        )

    def test_arbitrary_status_rejected_on_admin_endpoint(self, client, db):
        sysadmin = _make_user(db, "ev_status_admin@test.com", is_admin=True)
        org = _make_org(db)
        event = _make_event(db, org.id)

        resp = client.patch(
            f"/admin/events/{event.id}",
            json={"status": "published"},
            headers=_auth(sysadmin.id),
        )

        assert resp.status_code == 422, (
            f"Arbitrary status 'published' was accepted: HTTP {resp.status_code}"
        )

    def test_valid_status_active_is_accepted(self, client, db):
        cat = _make_category(db)
        owner = _make_user(db, "ev_status_active@test.com")
        org = _make_org(db)
        _make_owner(db, org.id, owner.id)
        event = _make_event(db, org.id)

        resp = client.put(
            f"/events/{event.id}",
            json={"status": "active", "category_ids": [cat.id]},
            headers=_auth(owner.id),
        )

        assert resp.status_code == 200, (
            f"Valid status 'active' was rejected: HTTP {resp.status_code}, {resp.json()}"
        )

    def test_valid_status_cancelled_is_accepted(self, client, db):
        cat = _make_category(db)
        owner = _make_user(db, "ev_status_cancel@test.com")
        org = _make_org(db)
        _make_owner(db, org.id, owner.id)
        event = _make_event(db, org.id)

        resp = client.put(
            f"/events/{event.id}",
            json={"status": "cancelled", "category_ids": [cat.id]},
            headers=_auth(owner.id),
        )

        assert resp.status_code == 200, (
            f"Valid status 'cancelled' was rejected: HTTP {resp.status_code}, {resp.json()}"
        )
        assert resp.json()["status"] == "cancelled"

    def test_omitting_status_keeps_existing_status(self, client, db):
        """Not sending status at all (the Flutter pattern) must leave event status unchanged."""
        cat = _make_category(db)
        owner = _make_user(db, "ev_status_omit@test.com")
        org = _make_org(db)
        _make_owner(db, org.id, owner.id)
        event = _make_event(db, org.id)

        resp = client.put(
            f"/events/{event.id}",
            json={"title": "Updated title", "category_ids": [cat.id]},
            headers=_auth(owner.id),
        )

        assert resp.status_code == 200, (
            f"Update without status was rejected: HTTP {resp.status_code}, {resp.json()}"
        )
        assert resp.json()["status"] == "active"


# ═══════════════════════════════════════════════════════════════════════════════
# P3-2: GET /notifications/ pagination
# ═══════════════════════════════════════════════════════════════════════════════

class TestNotificationsPagination:
    """
    Regression: GET /notifications/ returned all notifications without limit.
    After the fix, limit and offset params cap the response.
    """

    def test_default_limit_applied(self, client, db):
        """With default limit=100, more than 100 notifications are truncated."""
        user = _make_user(db, "notif_limit@test.com")
        for i in range(110):
            _make_notification(db, user.id, n=i)

        resp = client.get("/notifications/", headers=_auth(user.id))

        assert resp.status_code == 200
        assert len(resp.json()) == 100, (
            f"Expected at most 100 notifications, got {len(resp.json())}"
        )

    def test_explicit_limit(self, client, db):
        user = _make_user(db, "notif_explicit@test.com")
        for i in range(20):
            _make_notification(db, user.id, n=i)

        resp = client.get("/notifications/?limit=5", headers=_auth(user.id))

        assert resp.status_code == 200
        assert len(resp.json()) == 5

    def test_offset_paginates(self, client, db):
        user = _make_user(db, "notif_offset@test.com")
        for i in range(10):
            _make_notification(db, user.id, n=i)

        first = client.get("/notifications/?limit=5&offset=0", headers=_auth(user.id))
        second = client.get("/notifications/?limit=5&offset=5", headers=_auth(user.id))

        assert first.status_code == 200
        assert second.status_code == 200
        ids_first = {n["id"] for n in first.json()}
        ids_second = {n["id"] for n in second.json()}
        assert ids_first.isdisjoint(ids_second), "Pages overlap — offset is not working"

    def test_limit_above_max_rejected(self, client, db):
        user = _make_user(db, "notif_max@test.com")

        resp = client.get("/notifications/?limit=201", headers=_auth(user.id))

        assert resp.status_code == 422

    def test_response_is_still_a_list(self, client, db):
        """Response format must remain a plain list (not a paginated object)."""
        user = _make_user(db, "notif_list@test.com")
        _make_notification(db, user.id)

        resp = client.get("/notifications/", headers=_auth(user.id))

        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ═══════════════════════════════════════════════════════════════════════════════
# P3-3: GET /events/ bounded list
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventsDefaultLimit:
    """
    Regression: GET /events/ returned unlimited results.
    After the fix, default limit=500 is applied; response remains a list.
    """

    def test_default_limit_caps_results(self, client, db):
        org = _make_org(db)
        for i in range(510):
            _make_event(db, org.id, title=f"Event {i}")

        resp = client.get("/events/")

        assert resp.status_code == 200
        assert len(resp.json()) <= 500, (
            f"Expected at most 500 events, got {len(resp.json())}"
        )

    def test_explicit_limit_respected(self, client, db):
        org = _make_org(db)
        for i in range(20):
            _make_event(db, org.id, title=f"Event {i}")

        resp = client.get("/events/?limit=5")

        assert resp.status_code == 200
        assert len(resp.json()) == 5

    def test_limit_above_max_rejected(self, client, db):
        resp = client.get("/events/?limit=1001")
        assert resp.status_code == 422

    def test_response_is_still_a_list(self, client, db):
        resp = client.get("/events/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ═══════════════════════════════════════════════════════════════════════════════
# P3-4: Review image count cap
# ═══════════════════════════════════════════════════════════════════════════════

class TestReviewImageCountCap:
    """
    Regression: POST /review-images/ had no per-review image count limit.
    After the fix, uploading a 6th image must be rejected with HTTP 400.
    """

    def test_fifth_image_accepted(self, client, db):
        """The 5th image must still be accepted."""
        author = _make_user(db, "img_fifth@test.com")
        org = _make_org(db)
        review = _make_review(db, author.id, org.id)
        for i in range(4):
            _make_image(db, review.id, n=i)

        resp = client.post(
            "/review-images/",
            json={"review_id": review.id, "image_url": "https://example.com/5th.jpg"},
            headers=_auth(author.id),
        )

        assert resp.status_code == 200, (
            f"5th image was rejected: HTTP {resp.status_code}, {resp.json()}"
        )

    def test_sixth_image_rejected(self, client, db):
        """
        Regression: a 6th image was accepted before the fix.
        After the fix, it must be rejected with HTTP 400.
        """
        author = _make_user(db, "img_sixth@test.com")
        org = _make_org(db)
        review = _make_review(db, author.id, org.id)
        for i in range(5):
            _make_image(db, review.id, n=i)

        resp = client.post(
            "/review-images/",
            json={"review_id": review.id, "image_url": "https://example.com/6th.jpg"},
            headers=_auth(author.id),
        )

        assert resp.status_code == 400, (
            f"6th image was accepted (expected 400): HTTP {resp.status_code}"
        )

    def test_first_image_always_accepted(self, client, db):
        author = _make_user(db, "img_first@test.com")
        org = _make_org(db)
        review = _make_review(db, author.id, org.id)

        resp = client.post(
            "/review-images/",
            json={"review_id": review.id, "image_url": "https://example.com/1st.jpg"},
            headers=_auth(author.id),
        )

        assert resp.status_code == 200

    def test_cap_is_per_review_not_global(self, client, db):
        """The 5-image cap applies per review; a different review is unaffected."""
        author = _make_user(db, "img_per_review@test.com")
        org = _make_org(db)
        review_a = _make_review(db, author.id, org.id)
        review_b = _make_review(db, author.id, org.id)

        # Fill review_a to the limit
        for i in range(5):
            _make_image(db, review_a.id, n=i)

        # review_b should still accept images
        resp = client.post(
            "/review-images/",
            json={"review_id": review_b.id, "image_url": "https://example.com/b.jpg"},
            headers=_auth(author.id),
        )

        assert resp.status_code == 200, (
            f"Image for different review rejected: HTTP {resp.status_code}"
        )

    def test_sysadmin_also_subject_to_cap(self, client, db):
        """System admins are also subject to the per-review image cap."""
        sysadmin = _make_user(db, "img_sysadmin@test.com", is_admin=True)
        author = _make_user(db, "img_author@test.com")
        org = _make_org(db)
        review = _make_review(db, author.id, org.id)
        for i in range(5):
            _make_image(db, review.id, n=i)

        resp = client.post(
            "/review-images/",
            json={"review_id": review.id, "image_url": "https://example.com/admin6.jpg"},
            headers=_auth(sysadmin.id),
        )

        assert resp.status_code == 400, (
            f"Sysadmin bypassed image cap: HTTP {resp.status_code}"
        )
