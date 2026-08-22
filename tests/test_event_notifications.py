"""
Tests for event-driven alert notifications:
  - new_event  (POST /events/)
  - event_updated  (PUT /events/{id} — meaningful field change)
  - event_cancelled  (PUT /events/{id} — status → "cancelled")
"""
import json
from datetime import datetime

from app.core.security import create_access_token
from app.models.category import Category
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.favorite import Favorite
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email):
    u = User(email=email, name="Test", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, owner: User):
    org = Organization(name="HobbyOrg", status="active", verified=True)
    db.add(org)
    db.flush()
    db.add(OrganizationUser(organization_id=org.id, user_id=owner.id, role="owner"))
    db.commit()
    db.refresh(org)
    return org


def _make_category(db):
    cat = Category(name="Sport")
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _make_event_direct(db, org_id, category_id, title="My Event"):
    ev = Event(
        organization_id=org_id,
        title=title,
        start_datetime=datetime(2099, 6, 1, 10, 0),
        status="active",
        category_id=category_id,
    )
    db.add(ev)
    db.flush()
    db.add(EventCategory(event_id=ev.id, category_id=category_id, position=0))
    db.commit()
    db.refresh(ev)
    return ev


def _favorite(db, user_id, entity_type, entity_id):
    f = Favorite(user_id=user_id, entity_type=entity_type, entity_id=entity_id)
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def _auth(user: User):
    token = create_access_token({"user_id": user.id})
    return {"Authorization": f"Bearer {token}"}


def _event_payload(org_id, category_id, **kwargs):
    body = {
        "organization_id": org_id,
        "title": "New Event",
        "start_datetime": "2099-06-01T10:00:00",
        "category_ids": [category_id],
    }
    body.update(kwargs)
    return body


def _notifications_for(db, user_id, notif_type):
    db.expire_all()
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.type == notif_type)
        .all()
    )


# ── new_event ─────────────────────────────────────────────────────────────────

def test_new_event_org_follower_receives_notification(client, db):
    """Org follower receives a new_event notification after a new event is created."""
    creator = _make_user(db, "creator@t.com")
    follower = _make_user(db, "follower@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    _favorite(db, follower.id, "organization", org.id)

    resp = client.post("/events/", json=_event_payload(org.id, cat.id), headers=_auth(creator))
    assert resp.status_code == 200

    notifications = _notifications_for(db, follower.id, "new_event")
    assert len(notifications) == 1
    assert notifications[0].title == "notification.new_event.title"
    assert notifications[0].message == "notification.new_event.body"


def test_new_event_creator_not_notified(client, db):
    """The event creator does not receive a new_event notification even if they follow the org."""
    creator = _make_user(db, "creator2@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    _favorite(db, creator.id, "organization", org.id)

    resp = client.post("/events/", json=_event_payload(org.id, cat.id), headers=_auth(creator))
    assert resp.status_code == 200

    assert len(_notifications_for(db, creator.id, "new_event")) == 0


def test_new_event_org_owner_not_notified(client, db):
    """Org owner is excluded from new_event even when a different member creates the event."""
    owner = _make_user(db, "owner3@t.com")
    admin = _make_user(db, "admin3@t.com")
    follower = _make_user(db, "follower3@t.com")
    org = _make_org(db, owner)
    db.add(OrganizationUser(organization_id=org.id, user_id=admin.id, role="admin"))
    db.commit()

    cat = _make_category(db)
    _favorite(db, owner.id, "organization", org.id)
    _favorite(db, follower.id, "organization", org.id)

    resp = client.post("/events/", json=_event_payload(org.id, cat.id), headers=_auth(admin))
    assert resp.status_code == 200

    assert len(_notifications_for(db, owner.id, "new_event")) == 0
    assert len(_notifications_for(db, follower.id, "new_event")) == 1


def test_new_event_no_followers_no_notifications(client, db):
    """No notifications are created when nobody follows the organization."""
    creator = _make_user(db, "creator4@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)

    resp = client.post("/events/", json=_event_payload(org.id, cat.id), headers=_auth(creator))
    assert resp.status_code == 200

    db.expire_all()
    total = db.query(Notification).filter(Notification.type == "new_event").count()
    assert total == 0


def test_new_event_notification_payload(client, db):
    """new_event payload JSON contains event_id, event_title, and organization_name."""
    creator = _make_user(db, "creator5@t.com")
    follower = _make_user(db, "follower5@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    _favorite(db, follower.id, "organization", org.id)

    resp = client.post(
        "/events/",
        json=_event_payload(org.id, cat.id, title="Yoga Class"),
        headers=_auth(creator),
    )
    assert resp.status_code == 200
    event_id = resp.json()["id"]

    notifications = _notifications_for(db, follower.id, "new_event")
    assert len(notifications) == 1
    payload = json.loads(notifications[0].payload)
    assert payload["event_id"] == event_id
    assert payload["event_title"] == "Yoga Class"
    assert payload["organization_name"] == "HobbyOrg"


# ── event_updated ─────────────────────────────────────────────────────────────

def test_event_updated_meaningful_change_notifies_favorers(client, db):
    """A meaningful field change (title) creates event_updated for event favorers."""
    creator = _make_user(db, "creator6@t.com")
    follower = _make_user(db, "follower6@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    ev = _make_event_direct(db, org.id, cat.id, title="Old Title")
    _favorite(db, follower.id, "event", ev.id)

    resp = client.put(
        f"/events/{ev.id}",
        json={"title": "New Title"},
        headers=_auth(creator),
    )
    assert resp.status_code == 200

    notifications = _notifications_for(db, follower.id, "event_updated")
    assert len(notifications) == 1
    assert notifications[0].title == "notification.event_updated.title"
    payload = json.loads(notifications[0].payload)
    assert payload["event_id"] == ev.id
    assert payload["event_title"] == "Old Title"


def test_event_updated_actor_not_notified(client, db):
    """The user who performs the update is not notified even if they favorited the event."""
    creator = _make_user(db, "creator7@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    ev = _make_event_direct(db, org.id, cat.id)
    _favorite(db, creator.id, "event", ev.id)

    resp = client.put(
        f"/events/{ev.id}",
        json={"title": "Updated"},
        headers=_auth(creator),
    )
    assert resp.status_code == 200

    assert len(_notifications_for(db, creator.id, "event_updated")) == 0


def test_event_updated_cosmetic_change_no_notification(client, db):
    """Changing only image_url (not in meaningful fields) creates no notification."""
    creator = _make_user(db, "creator8@t.com")
    follower = _make_user(db, "follower8@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    ev = _make_event_direct(db, org.id, cat.id)
    _favorite(db, follower.id, "event", ev.id)

    resp = client.put(
        f"/events/{ev.id}",
        json={"image_url": "https://example.com/img.jpg"},
        headers=_auth(creator),
    )
    assert resp.status_code == 200

    assert len(_notifications_for(db, follower.id, "event_updated")) == 0


def test_event_updated_no_favorers_no_notifications(client, db):
    """No notifications when nobody has favorited the event."""
    creator = _make_user(db, "creator9@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    ev = _make_event_direct(db, org.id, cat.id)

    resp = client.put(
        f"/events/{ev.id}",
        json={"title": "Changed"},
        headers=_auth(creator),
    )
    assert resp.status_code == 200

    db.expire_all()
    assert db.query(Notification).filter(Notification.type == "event_updated").count() == 0


# ── event_cancelled ───────────────────────────────────────────────────────────

def test_event_cancelled_notifies_favorers(client, db):
    """Setting status=cancelled creates event_cancelled for event favorers."""
    creator = _make_user(db, "creator10@t.com")
    follower = _make_user(db, "follower10@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    ev = _make_event_direct(db, org.id, cat.id, title="Swim Class")
    _favorite(db, follower.id, "event", ev.id)

    resp = client.put(
        f"/events/{ev.id}",
        json={"status": "cancelled"},
        headers=_auth(creator),
    )
    assert resp.status_code == 200

    notifications = _notifications_for(db, follower.id, "event_cancelled")
    assert len(notifications) == 1
    assert notifications[0].title == "notification.event_cancelled.title"
    payload = json.loads(notifications[0].payload)
    assert payload["event_id"] == ev.id
    assert payload["event_title"] == "Swim Class"


def test_event_cancelled_not_event_updated(client, db):
    """Cancellation creates event_cancelled only — NOT also event_updated."""
    creator = _make_user(db, "creator11@t.com")
    follower = _make_user(db, "follower11@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    ev = _make_event_direct(db, org.id, cat.id)
    _favorite(db, follower.id, "event", ev.id)

    resp = client.put(
        f"/events/{ev.id}",
        json={"status": "cancelled"},
        headers=_auth(creator),
    )
    assert resp.status_code == 200

    assert len(_notifications_for(db, follower.id, "event_cancelled")) == 1
    assert len(_notifications_for(db, follower.id, "event_updated")) == 0


def test_event_cancelled_actor_not_notified(client, db):
    """The canceller is not notified even if they favorited the event."""
    creator = _make_user(db, "creator12@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    ev = _make_event_direct(db, org.id, cat.id)
    _favorite(db, creator.id, "event", ev.id)

    resp = client.put(
        f"/events/{ev.id}",
        json={"status": "cancelled"},
        headers=_auth(creator),
    )
    assert resp.status_code == 200

    assert len(_notifications_for(db, creator.id, "event_cancelled")) == 0


def test_already_cancelled_no_duplicate_notification(client, db):
    """Re-cancelling an already-cancelled event creates no additional notification."""
    creator = _make_user(db, "creator13@t.com")
    follower = _make_user(db, "follower13@t.com")
    org = _make_org(db, creator)
    cat = _make_category(db)
    ev = _make_event_direct(db, org.id, cat.id)
    ev.status = "cancelled"
    db.commit()
    _favorite(db, follower.id, "event", ev.id)

    resp = client.put(
        f"/events/{ev.id}",
        json={"status": "cancelled"},
        headers=_auth(creator),
    )
    assert resp.status_code == 200

    assert len(_notifications_for(db, follower.id, "event_cancelled")) == 0


# ── alert_count / message_count ───────────────────────────────────────────────

def test_event_notifications_counted_in_alert_count(client, db):
    """event_updated, event_cancelled, and new_event all appear in alert_count."""
    user = _make_user(db, "counter@t.com")

    for notif_type in ("event_updated", "event_cancelled", "new_event"):
        n = Notification(user_id=user.id, type=notif_type, title="t", message="m")
        db.add(n)
    db.commit()

    data = client.get("/notifications/unread-count", headers=_auth(user)).json()
    assert data["alert_count"] == 3
    assert data["message_count"] == 0


def test_event_notifications_not_in_message_count(client, db):
    """event_updated, event_cancelled, and new_event do not appear in message_count."""
    user = _make_user(db, "notmsg@t.com")

    for notif_type in ("event_updated", "event_cancelled", "new_event"):
        n = Notification(user_id=user.id, type=notif_type, title="t", message="m")
        db.add(n)
    db.commit()

    data = client.get("/notifications/unread-count", headers=_auth(user)).json()
    assert data["message_count"] == 0
