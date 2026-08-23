"""
Tests for:
  - POST /conversations/{id}/read
  - GET /notifications/unread-count  (split response)
  - admin user_id=1 no longer hardcoded in org creation
"""
from app.core.security import create_access_token
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.schemas.conversation import ConversationResponse


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="u@test.com", name="User"):
    u = User(email=email, name=name, password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, owner: User):
    org = Organization(name="Test Org", status="active", verified=True)
    db.add(org)
    db.flush()
    db.add(OrganizationUser(organization_id=org.id, user_id=owner.id, role="owner"))
    db.commit()
    db.refresh(org)
    return org


def _make_conversation(db, user: User, org: Organization):
    conv = Conversation(user_id=user.id, organization_id=org.id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _make_message(db, conversation_id: int, sender_id: int, text="hello"):
    msg = Message(
        conversation_id=conversation_id,
        sender_type="user",
        sender_id=sender_id,
        message_text=text,
        read_at=None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def _make_notification(db, user_id: int, notif_type: str, conversation_id=None, is_read=False):
    n = Notification(
        user_id=user_id,
        type=notif_type,
        title="t",
        message="m",
        conversation_id=conversation_id,
        is_read=is_read,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def _auth(user: User):
    token = create_access_token({"user_id": user.id})
    return {"Authorization": f"Bearer {token}"}


# ── mark conversation as read ─────────────────────────────────────────────────

def test_mark_conversation_read_sets_read_at(client, db):
    """Unread messages sent by the other side get read_at stamped."""
    user = _make_user(db, email="reader@test.com")
    owner = _make_user(db, email="owner@test.com")
    org = _make_org(db, owner)
    conv = _make_conversation(db, user, org)

    # Two messages sent by the org owner (not the user); should be marked read.
    msg1 = _make_message(db, conv.id, sender_id=owner.id, text="hi")
    msg2 = _make_message(db, conv.id, sender_id=owner.id, text="there")
    # One message sent by the user themselves; must NOT be marked read.
    own_msg = _make_message(db, conv.id, sender_id=user.id, text="reply")

    resp = client.post(f"/conversations/{conv.id}/read", headers=_auth(user))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    db.expire_all()
    assert db.query(Message).get(msg1.id).read_at is not None
    assert db.query(Message).get(msg2.id).read_at is not None
    # User's own message must remain untouched.
    assert db.query(Message).get(own_msg.id).read_at is None


def test_mark_conversation_read_clears_message_notifications(client, db):
    """Unread message-type notifications for the conversation become is_read=True."""
    user = _make_user(db, email="notif_reader@test.com")
    owner = _make_user(db, email="notif_owner@test.com")
    org = _make_org(db, owner)
    conv = _make_conversation(db, user, org)

    n1 = _make_notification(db, user.id, "message", conversation_id=conv.id)
    n2 = _make_notification(db, user.id, "message", conversation_id=conv.id)
    # Notification for a different conversation — must remain unread.
    other_conv = _make_conversation(db, user, org)
    n_other = _make_notification(db, user.id, "message", conversation_id=other_conv.id)

    resp = client.post(f"/conversations/{conv.id}/read", headers=_auth(user))
    assert resp.status_code == 200

    db.expire_all()
    assert db.query(Notification).get(n1.id).is_read is True
    assert db.query(Notification).get(n2.id).is_read is True
    assert db.query(Notification).get(n_other.id).is_read is False


def test_mark_conversation_read_ignores_already_read(client, db):
    """Already-read notifications are unaffected (no error)."""
    user = _make_user(db, email="already_read@test.com")
    owner = _make_user(db, email="already_owner@test.com")
    org = _make_org(db, owner)
    conv = _make_conversation(db, user, org)
    _make_notification(db, user.id, "message", conversation_id=conv.id, is_read=True)

    resp = client.post(f"/conversations/{conv.id}/read", headers=_auth(user))
    assert resp.status_code == 200


def test_mark_conversation_read_forbidden_for_unrelated_user(client, db):
    """A user with no access to the conversation gets 403."""
    owner = _make_user(db, email="owner2@test.com")
    stranger = _make_user(db, email="stranger@test.com")
    org = _make_org(db, owner)
    user = _make_user(db, email="conv_user@test.com")
    conv = _make_conversation(db, user, org)

    resp = client.post(f"/conversations/{conv.id}/read", headers=_auth(stranger))
    assert resp.status_code == 403


def test_mark_conversation_read_not_found(client, db):
    user = _make_user(db, email="nf@test.com")
    resp = client.post("/conversations/99999/read", headers=_auth(user))
    assert resp.status_code == 404


def test_mark_conversation_read_org_side(client, db):
    """Org owner/admin can also mark the conversation as read from their side."""
    user = _make_user(db, email="client_user@test.com")
    owner = _make_user(db, email="org_owner@test.com")
    org = _make_org(db, owner)
    conv = _make_conversation(db, user, org)

    # Message sent by the user (client side) — org owner should mark it read.
    msg = _make_message(db, conv.id, sender_id=user.id, text="question")
    notif = _make_notification(db, owner.id, "message", conversation_id=conv.id)

    resp = client.post(f"/conversations/{conv.id}/read", headers=_auth(owner))
    assert resp.status_code == 200

    db.expire_all()
    assert db.query(Message).get(msg.id).read_at is not None
    assert db.query(Notification).get(notif.id).is_read is True


# ── unread-count split ────────────────────────────────────────────────────────

def test_unread_message_counts_in_message_count_only(client, db):
    user = _make_user(db, email="count_msg@test.com")
    _make_notification(db, user.id, "message")
    _make_notification(db, user.id, "message")

    data = client.get("/notifications/unread-count", headers=_auth(user)).json()
    assert data["message_count"] == 2
    assert data["alert_count"] == 0


def test_unread_normal_alert_counts_in_alert_count_only(client, db):
    user = _make_user(db, email="count_alert@test.com")
    _make_notification(db, user.id, "promo")
    _make_notification(db, user.id, "promo")
    _make_notification(db, user.id, "promo")

    data = client.get("/notifications/unread-count", headers=_auth(user)).json()
    assert data["message_count"] == 0
    assert data["alert_count"] == 3


def test_unread_new_organization_counted_in_neither(client, db):
    user = _make_user(db, email="count_neworg@test.com")
    _make_notification(db, user.id, "new_organization")
    _make_notification(db, user.id, "new_organization")

    data = client.get("/notifications/unread-count", headers=_auth(user)).json()
    assert data["message_count"] == 0
    assert data["alert_count"] == 0


def test_read_notifications_counted_in_neither(client, db):
    user = _make_user(db, email="count_read2@test.com")
    _make_notification(db, user.id, "message", is_read=True)
    _make_notification(db, user.id, "promo", is_read=True)
    _make_notification(db, user.id, "new_organization", is_read=True)

    data = client.get("/notifications/unread-count", headers=_auth(user)).json()
    assert data == {"message_count": 0, "alert_count": 0}


def test_unread_count_mixed_types(client, db):
    """All three types together; new_organization must not appear in either count."""
    user = _make_user(db, email="count_mixed@test.com")
    _make_notification(db, user.id, "message")
    _make_notification(db, user.id, "message")
    _make_notification(db, user.id, "promo")
    _make_notification(db, user.id, "new_organization")
    _make_notification(db, user.id, "new_organization")

    data = client.get("/notifications/unread-count", headers=_auth(user)).json()
    assert data["message_count"] == 2
    assert data["alert_count"] == 1


def test_unread_count_zero_when_all_read(client, db):
    user = _make_user(db, email="all_read@test.com")
    _make_notification(db, user.id, "message", is_read=True)
    _make_notification(db, user.id, "promo", is_read=True)
    _make_notification(db, user.id, "new_organization", is_read=True)

    assert client.get("/notifications/unread-count", headers=_auth(user)).json() == {
        "message_count": 0,
        "alert_count": 0,
    }


def test_unread_count_is_per_user(client, db):
    """One user's notifications do not appear in another user's count."""
    user_a = _make_user(db, email="ua@test.com")
    user_b = _make_user(db, email="ub@test.com")

    _make_notification(db, user_a.id, "message")
    _make_notification(db, user_a.id, "message")

    resp = client.get("/notifications/unread-count", headers=_auth(user_b))
    assert resp.status_code == 200
    assert resp.json() == {"message_count": 0, "alert_count": 0}


def test_unread_count_after_mark_conversation_read(client, db):
    """After POST /conversations/{id}/read the message_count drops."""
    user = _make_user(db, email="drop_count@test.com")
    owner = _make_user(db, email="drop_owner@test.com")
    org = _make_org(db, owner)
    conv = _make_conversation(db, user, org)

    _make_notification(db, user.id, "message", conversation_id=conv.id)
    _make_notification(db, user.id, "message", conversation_id=conv.id)

    before = client.get("/notifications/unread-count", headers=_auth(user)).json()
    assert before["message_count"] == 2

    client.post(f"/conversations/{conv.id}/read", headers=_auth(user))

    after = client.get("/notifications/unread-count", headers=_auth(user)).json()
    assert after["message_count"] == 0


# ── conversations list: organization_name ─────────────────────────────────────

def test_conversations_list_includes_org_name(client, db):
    """GET /conversations/ includes organization_name for each conversation."""
    user = _make_user(db, "cvlist@test.com")
    owner = _make_user(db, "cvlist_owner@test.com")
    org = _make_org(db, owner)
    conv = _make_conversation(db, user, org)
    _make_message(db, conv.id, sender_id=owner.id)

    resp = client.get("/conversations/", headers=_auth(user))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["organization_name"] == "Test Org"


def test_create_conversation_includes_org_name(client, db):
    """POST /conversations/ returns organization_name in the response."""
    user = _make_user(db, "cvcreate@test.com")
    owner = _make_user(db, "cvcreate_owner@test.com")
    org = _make_org(db, owner)

    resp = client.post("/conversations/", json={"organization_id": org.id}, headers=_auth(user))
    assert resp.status_code == 200
    assert resp.json()["organization_name"] == "Test Org"


def test_create_existing_conversation_includes_org_name(client, db):
    """POST /conversations/ on an already-existing conversation still returns organization_name."""
    user = _make_user(db, "cvexist@test.com")
    owner = _make_user(db, "cvexist_owner@test.com")
    org = _make_org(db, owner)
    _make_conversation(db, user, org)

    resp = client.post("/conversations/", json={"organization_id": org.id}, headers=_auth(user))
    assert resp.status_code == 200
    assert resp.json()["organization_name"] == "Test Org"


def test_conversations_list_multiple_orgs_correct_names(client, db):
    """GET /conversations/ with multiple conversations returns each org's correct name."""
    user = _make_user(db, "cvmulti@test.com")
    owner1 = _make_user(db, "cvmulti_o1@test.com")
    owner2 = _make_user(db, "cvmulti_o2@test.com")
    org1 = _make_org(db, owner1)  # name = "Test Org"

    org2 = Organization(name="Dance Studio", status="active", verified=True)
    db.add(org2)
    db.flush()
    db.add(OrganizationUser(organization_id=org2.id, user_id=owner2.id, role="owner"))
    db.commit()
    db.refresh(org2)

    conv1 = _make_conversation(db, user, org1)
    conv2 = _make_conversation(db, user, org2)
    _make_message(db, conv1.id, sender_id=owner1.id)
    _make_message(db, conv2.id, sender_id=owner2.id)

    resp = client.get("/conversations/", headers=_auth(user))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = {d["organization_name"] for d in data}
    assert names == {"Test Org", "Dance Studio"}

