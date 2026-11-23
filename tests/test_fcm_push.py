"""
Regression tests for FCM push notification infrastructure.

Tests cover:
  - Device token registration, reassignment on account switch, and removal.
  - Device token deletion on account deletion.
  - Locale sync endpoint.
  - Push preference enforcement (disabled pref → no FCM call).
  - FCM failure does not break message sending.
  - Invalid token removal after FCM reports it stale.
  - Localized push text (EN / RU / HE).
"""
import json
from unittest.mock import patch

from app.core.security import create_access_token
from app.models.device_token import DeviceToken
from app.models.user import User
from app.models.user_auth_provider import UserAuthProvider


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email, preferred_locale="en", notif_chat=True, notif_activity=True):
    u = User(
        email=email,
        name="Test",
        password_hash=None,
        status="active",
        preferred_locale=preferred_locale,
        notif_chat=notif_chat,
        notif_activity=notif_activity,
        token_version=0,
    )
    db.add(u)
    db.flush()
    ap = UserAuthProvider(
        user_id=u.id,
        provider="google",
        provider_user_id=f"google_{email}",
        provider_email=email,
    )
    db.add(ap)
    db.commit()
    db.refresh(u)
    return u


def _auth(user):
    tv = user.token_version or 0
    return {"Authorization": f"Bearer {create_access_token({'user_id': user.id, 'tv': tv})}"}


def _add_token(db, user, token, platform="android"):
    dt = DeviceToken(user_id=user.id, token=token, platform=platform)
    db.add(dt)
    db.commit()
    return dt


# ── device token registration ─────────────────────────────────────────────────

def test_register_device_token_creates_row(client, db):
    user = _make_user(db, "reg_token@test.com")
    resp = client.post("/me/device-token", json={"token": "tok_abc123"}, headers=_auth(user))
    assert resp.status_code == 200
    assert db.query(DeviceToken).filter_by(token="tok_abc123", user_id=user.id).first() is not None


def test_register_device_token_idempotent(client, db):
    user = _make_user(db, "reg_idem@test.com")
    client.post("/me/device-token", json={"token": "tok_idem"}, headers=_auth(user))
    resp = client.post("/me/device-token", json={"token": "tok_idem"}, headers=_auth(user))
    assert resp.status_code == 200
    assert db.query(DeviceToken).filter_by(token="tok_idem").count() == 1


def test_register_token_reassignment_on_account_switch(client, db):
    """Token that belonged to user A must be reassigned to user B after B registers it."""
    user_a = _make_user(db, "switch_a@test.com")
    user_b = _make_user(db, "switch_b@test.com")

    _add_token(db, user_a, "shared_token")

    resp = client.post("/me/device-token", json={"token": "shared_token"}, headers=_auth(user_b))
    assert resp.status_code == 200

    dt = db.query(DeviceToken).filter_by(token="shared_token").first()
    assert dt is not None
    assert dt.user_id == user_b.id, "Token must be reassigned to new user"


def test_register_device_token_requires_auth(client, db):
    resp = client.post("/me/device-token", json={"token": "tok_unauth"})
    assert resp.status_code == 401


def test_remove_device_token(client, db):
    user = _make_user(db, "remove_tok@test.com")
    _add_token(db, user, "tok_to_remove")

    resp = client.request("DELETE", "/me/device-token", json={"token": "tok_to_remove"}, headers=_auth(user))
    assert resp.status_code == 200
    assert db.query(DeviceToken).filter_by(token="tok_to_remove").first() is None


def test_remove_device_token_other_user_ignored(client, db):
    """DELETE /me/device-token must not remove another user's token."""
    owner = _make_user(db, "owner_tok@test.com")
    other = _make_user(db, "other_tok@test.com")
    _add_token(db, owner, "tok_owner_only")

    resp = client.request("DELETE", "/me/device-token", json={"token": "tok_owner_only"}, headers=_auth(other))
    assert resp.status_code == 200
    assert db.query(DeviceToken).filter_by(token="tok_owner_only").first() is not None


def test_delete_account_removes_device_tokens(client, db):
    user = _make_user(db, "del_tok@test.com")
    _add_token(db, user, "tok_del1")
    _add_token(db, user, "tok_del2")

    resp = client.delete("/me", headers=_auth(user))
    assert resp.status_code == 204
    assert db.query(DeviceToken).filter_by(user_id=user.id).count() == 0


# ── locale sync ───────────────────────────────────────────────────────────────

def test_update_locale_valid(client, db):
    user = _make_user(db, "locale_update@test.com")
    resp = client.put("/me/locale", json={"locale": "he"}, headers=_auth(user))
    assert resp.status_code == 200
    db.refresh(user)
    assert user.preferred_locale == "he"


def test_update_locale_all_supported(client, db):
    user = _make_user(db, "locale_all@test.com")
    for locale in ("en", "ru", "he"):
        resp = client.put("/me/locale", json={"locale": locale}, headers=_auth(user))
        assert resp.status_code == 200


def test_update_locale_invalid_rejected(client, db):
    user = _make_user(db, "locale_bad@test.com")
    resp = client.put("/me/locale", json={"locale": "fr"}, headers=_auth(user))
    assert resp.status_code == 400


# ── preference enforcement ────────────────────────────────────────────────────

def test_push_respects_notif_chat_false(db):
    """Users with notif_chat=False must not receive a push for new messages."""
    from app.core.push_notifications import push_new_message

    user = _make_user(db, "nochat_push@test.com", notif_chat=False)
    _add_token(db, user, "tok_nochat")

    with patch("app.core.push_notifications.fcm_module.send_to_tokens") as mock_send:
        push_new_message({user.id}, db)
        mock_send.assert_not_called()


def test_push_respects_notif_chat_true(db):
    """Users with notif_chat=True and a token must receive a push."""
    from app.core.push_notifications import push_new_message

    user = _make_user(db, "yeschat_push@test.com", notif_chat=True)
    _add_token(db, user, "tok_yeschat")

    with patch("app.core.push_notifications.fcm_module.send_to_tokens", return_value=[]) as mock_send:
        push_new_message({user.id}, db)
        mock_send.assert_called_once()
        _, title, body, _ = mock_send.call_args[0]
        assert title == "New message"


def test_push_respects_notif_activity_false(db):
    from app.core.push_notifications import push_event_updated

    user = _make_user(db, "noact_push@test.com", notif_activity=False)
    _add_token(db, user, "tok_noact")

    with patch("app.core.push_notifications.fcm_module.send_to_tokens") as mock_send:
        push_event_updated({user.id}, 1, "Test Event", db)
        mock_send.assert_not_called()


def test_push_no_token_no_send(db):
    """Users without any device token must not trigger a send call."""
    from app.core.push_notifications import push_new_message

    user = _make_user(db, "notoken_push@test.com", notif_chat=True)
    # No DeviceToken row added

    with patch("app.core.push_notifications.fcm_module.send_to_tokens") as mock_send:
        push_new_message({user.id}, db)
        mock_send.assert_not_called()


# ── post-logout push suppression ─────────────────────────────────────────────

def test_no_push_after_token_removed_via_logout(db):
    """After DELETE /me/device-token succeeds (logout cleanup), no push is sent."""
    from app.core.push_notifications import push_new_message

    user = _make_user(db, "post_logout@test.com", notif_chat=True)
    _add_token(db, user, "tok_logout_cleanup")

    # Simulate successful logout cleanup: token removed
    db.query(DeviceToken).filter_by(token="tok_logout_cleanup").delete()
    db.commit()

    with patch("app.core.push_notifications.fcm_module.send_to_tokens") as mock_send:
        push_new_message({user.id}, db)
        mock_send.assert_not_called()


def test_deleted_user_gets_no_push(db):
    """Soft-deleted users have no device tokens; push_new_message must not send."""
    from app.core.push_notifications import push_new_message

    user = _make_user(db, "deleted_push@test.com", notif_chat=True)
    _add_token(db, user, "tok_before_delete")

    # Simulate account deletion: tokens are removed, status is set to deleted.
    db.query(DeviceToken).filter_by(user_id=user.id).delete()
    user.status = "deleted"
    db.commit()

    with patch("app.core.push_notifications.fcm_module.send_to_tokens") as mock_send:
        push_new_message({user.id}, db)
        mock_send.assert_not_called()


# ── in-app notification independence ─────────────────────────────────────────

def test_inapp_notification_created_even_when_push_disabled(client, db):
    """In-app Notification rows must be created regardless of notif_chat preference.

    This test verifies the fundamental design contract: in-app notifications
    are always preserved; push delivery is a separate, preference-gated layer.
    """
    from app.models.conversation import Conversation
    from app.models.notification import Notification
    from app.models.organization import Organization
    from app.models.organization_user import OrganizationUser

    # Recipient has chat notifications disabled (no push) but should still get
    # an in-app notification row.
    sender = _make_user(db, "inapp_sender@test.com")
    recipient = _make_user(db, "inapp_recipient@test.com", notif_chat=False)

    org = Organization(name="In-App Test Org", status="active")
    db.add(org)
    db.flush()
    db.add(OrganizationUser(organization_id=org.id, user_id=recipient.id, role="owner"))
    db.commit()

    conv = Conversation(user_id=sender.id, organization_id=org.id)
    db.add(conv)
    db.commit()

    with patch("app.core.push_notifications.fcm_module.send_to_tokens") as mock_send:
        resp = client.post(
            "/messages/",
            json={"conversation_id": conv.id, "message_text": "Hi there"},
            headers=_auth(sender),
        )
    assert resp.status_code == 200, resp.text

    # In-app notification row MUST exist
    notif = db.query(Notification).filter_by(user_id=recipient.id, type="message").first()
    assert notif is not None, "In-app notification must be created even when push is disabled"

    # Push must NOT have been sent
    mock_send.assert_not_called()


# ── FCM failure resilience ────────────────────────────────────────────────────

def test_fcm_failure_does_not_break_message_send(client, db):
    """If FCM raises, POST /messages must still return 200 and persist the message."""
    from app.models.conversation import Conversation
    from app.models.message import Message

    sender = _make_user(db, "fcm_fail_sender@test.com")
    recipient = _make_user(db, "fcm_fail_recipient@test.com")
    _add_token(db, recipient, "tok_fail_test")

    # Set recipient as notif_chat=True so the push path is exercised
    recipient.notif_chat = True
    db.commit()

    org_id = 1  # relies on a valid org existing; create one if needed
    from app.models.organization import Organization
    from app.models.organization_user import OrganizationUser
    org = Organization(name="FCM Fail Org", status="active")
    db.add(org)
    db.flush()
    db.add(OrganizationUser(organization_id=org.id, user_id=recipient.id, role="owner"))
    db.commit()

    conv = Conversation(user_id=sender.id, organization_id=org.id)
    db.add(conv)
    db.commit()

    with patch(
        "app.core.push_notifications.fcm_module.send_to_tokens",
        side_effect=Exception("FCM unreachable"),
    ):
        resp = client.post(
            "/messages/",
            json={"conversation_id": conv.id, "message_text": "Hello"},
            headers=_auth(sender),
        )

    assert resp.status_code == 200, resp.text
    assert db.query(Message).filter_by(conversation_id=conv.id).count() == 1


def test_invalid_token_removed_after_fcm_rejection(db):
    """Tokens that FCM reports as invalid must be deleted from device_tokens."""
    from app.core.push_notifications import push_new_message

    user = _make_user(db, "invalid_tok@test.com", notif_chat=True)
    _add_token(db, user, "tok_invalid_fcm")

    with patch(
        "app.core.push_notifications.fcm_module.send_to_tokens",
        return_value=["tok_invalid_fcm"],  # FCM says this token is stale
    ):
        push_new_message({user.id}, db)

    assert db.query(DeviceToken).filter_by(token="tok_invalid_fcm").first() is None


# ── localized push text ───────────────────────────────────────────────────────

def test_push_english_text(db):
    from app.core.push_notifications import push_new_message

    user = _make_user(db, "push_en@test.com", preferred_locale="en", notif_chat=True)
    _add_token(db, user, "tok_en_push")

    with patch("app.core.push_notifications.fcm_module.send_to_tokens", return_value=[]) as mock_send:
        push_new_message({user.id}, db)

    _, title, body, _ = mock_send.call_args[0]
    assert title == "New message"
    assert body == "You have a new message"


def test_push_russian_text(db):
    from app.core.push_notifications import push_new_message

    user = _make_user(db, "push_ru@test.com", preferred_locale="ru", notif_chat=True)
    _add_token(db, user, "tok_ru_push")

    with patch("app.core.push_notifications.fcm_module.send_to_tokens", return_value=[]) as mock_send:
        push_new_message({user.id}, db)

    _, title, body, _ = mock_send.call_args[0]
    assert title == "Новое сообщение"
    assert body == "У вас новое сообщение"


def test_push_hebrew_text(db):
    from app.core.push_notifications import push_new_message

    user = _make_user(db, "push_he@test.com", preferred_locale="he", notif_chat=True)
    _add_token(db, user, "tok_he_push")

    with patch("app.core.push_notifications.fcm_module.send_to_tokens", return_value=[]) as mock_send:
        push_new_message({user.id}, db)

    _, title, body, _ = mock_send.call_args[0]
    assert title == "הודעה חדשה"
    assert body == "יש לך הודעה חדשה"


def test_push_event_updated_localized(db):
    from app.core.push_notifications import push_event_updated

    user = _make_user(db, "push_event_ru@test.com", preferred_locale="ru", notif_activity=True)
    _add_token(db, user, "tok_event_ru")

    with patch("app.core.push_notifications.fcm_module.send_to_tokens", return_value=[]) as mock_send:
        push_event_updated({user.id}, 42, "Йога для начинающих", db)

    _, title, body, _ = mock_send.call_args[0]
    assert title == "Мероприятие обновлено"
    assert "Йога для начинающих" in body


def test_push_new_event_localized(db):
    from app.core.push_notifications import push_new_event

    user = _make_user(db, "push_new_event_he@test.com", preferred_locale="he", notif_activity=True)
    _add_token(db, user, "tok_new_event_he")

    with patch("app.core.push_notifications.fcm_module.send_to_tokens", return_value=[]) as mock_send:
        push_new_event({user.id}, 10, "אירוע ריקוד", "סטודיו X", db)

    _, title, body, _ = mock_send.call_args[0]
    assert "סטודיו X" in title
    assert "אירוע ריקוד" in body
