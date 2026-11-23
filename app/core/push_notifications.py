"""Per-user localized push notification sender.

Responsibilities:
  - Look up device tokens for target users.
  - Check per-user notification preferences before sending.
  - Resolve the user's preferred locale and format human-readable text.
  - Delegate FCM delivery to app.core.fcm.send_to_tokens.
  - Remove stale tokens that FCM reports as invalid.
  - Never raise — push failures must not affect the calling endpoint.

Call these functions AFTER db.commit() so no DB transaction is open during
the outbound FCM HTTP request.
"""
import logging
from typing import List, Set

from sqlalchemy.orm import Session

from app.core import fcm as fcm_module
from app.models.device_token import DeviceToken
from app.models.user import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Localized push strings — EN / RU / HE
# ---------------------------------------------------------------------------

_STRINGS: dict = {
    "en": {
        "new_message_title": "New message",
        "new_message_body": "You have a new message",
        "event_updated_title": "Event updated",
        "event_updated_body": "“{event_title}” has been updated",
        "event_cancelled_title": "Event cancelled",
        "event_cancelled_body": "“{event_title}” has been cancelled",
        "new_event_title": "New event from {organization_name}",
        "new_event_body": "{event_title}",
    },
    "ru": {
        "new_message_title": "Новое сообщение",
        "new_message_body": "У вас новое сообщение",
        "event_updated_title": "Мероприятие обновлено",
        "event_updated_body": "«{event_title}» было обновлено",
        "event_cancelled_title": "Мероприятие отменено",
        "event_cancelled_body": "«{event_title}» отменено",
        "new_event_title": "Новое мероприятие от {organization_name}",
        "new_event_body": "{event_title}",
    },
    "he": {
        "new_message_title": "הודעה חדשה",
        "new_message_body": "יש לך הודעה חדשה",
        "event_updated_title": "האירוע עודכן",
        "event_updated_body": "«{event_title}» עודכן",
        "event_cancelled_title": "האירוע בוטל",
        "event_cancelled_body": "«{event_title}» בוטל",
        "new_event_title": "אירוע חדש מאת {organization_name}",
        "new_event_body": "{event_title}",
    },
}


def _t(locale: str, key: str, **kwargs: str) -> str:
    strings = _STRINGS.get(locale) or _STRINGS["en"]
    template = strings.get(key) or _STRINGS["en"].get(key, key)
    return template.format(**kwargs) if kwargs else template


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_tokens(user_id: int, db: Session) -> List[str]:
    rows = db.query(DeviceToken.token).filter(DeviceToken.user_id == user_id).all()
    return [r.token for r in rows]


def _remove_invalid_tokens(invalid_tokens: List[str], db: Session) -> None:
    if not invalid_tokens:
        return
    try:
        db.query(DeviceToken).filter(
            DeviceToken.token.in_(invalid_tokens)
        ).delete(synchronize_session=False)
        db.commit()
    except Exception as exc:
        logger.error("remove_invalid_tokens_failed | error=%s", exc)
        db.rollback()


def _send_to_user(
    user: User,
    title: str,
    body: str,
    data: dict,
    db: Session,
) -> None:
    tokens = _get_tokens(user.id, db)
    if not tokens:
        return
    invalid = fcm_module.send_to_tokens(tokens, title, body, data)
    _remove_invalid_tokens(invalid, db)


# ---------------------------------------------------------------------------
# Public notification senders — call these AFTER db.commit()
# ---------------------------------------------------------------------------

def push_new_message(recipient_ids: Set[int], db: Session) -> None:
    """Send a chat-message push to users whose notif_chat preference is on."""
    for uid in recipient_ids:
        try:
            user = db.query(User).filter(User.id == uid).first()
            if not user or not user.notif_chat:
                continue
            locale = user.preferred_locale or "en"
            _send_to_user(
                user,
                title=_t(locale, "new_message_title"),
                body=_t(locale, "new_message_body"),
                data={"type": "message"},
                db=db,
            )
        except Exception as exc:
            logger.error("push_new_message_failed | user_id=%s | error=%s", uid, exc)


def push_event_updated(
    recipient_ids: Set[int],
    event_id: int,
    event_title: str,
    db: Session,
) -> None:
    """Send an event-updated push to users whose notif_activity preference is on."""
    for uid in recipient_ids:
        try:
            user = db.query(User).filter(User.id == uid).first()
            if not user or not user.notif_activity:
                continue
            locale = user.preferred_locale or "en"
            _send_to_user(
                user,
                title=_t(locale, "event_updated_title"),
                body=_t(locale, "event_updated_body", event_title=event_title),
                data={"type": "event_updated", "event_id": str(event_id)},
                db=db,
            )
        except Exception as exc:
            logger.error("push_event_updated_failed | user_id=%s | error=%s", uid, exc)


def push_event_cancelled(
    recipient_ids: Set[int],
    event_id: int,
    event_title: str,
    db: Session,
) -> None:
    """Send an event-cancelled push to users whose notif_activity preference is on."""
    for uid in recipient_ids:
        try:
            user = db.query(User).filter(User.id == uid).first()
            if not user or not user.notif_activity:
                continue
            locale = user.preferred_locale or "en"
            _send_to_user(
                user,
                title=_t(locale, "event_cancelled_title"),
                body=_t(locale, "event_cancelled_body", event_title=event_title),
                data={"type": "event_cancelled", "event_id": str(event_id)},
                db=db,
            )
        except Exception as exc:
            logger.error("push_event_cancelled_failed | user_id=%s | error=%s", uid, exc)


def push_new_event(
    recipient_ids: Set[int],
    event_id: int,
    event_title: str,
    organization_name: str,
    db: Session,
) -> None:
    """Send a new-event push to users whose notif_activity preference is on."""
    for uid in recipient_ids:
        try:
            user = db.query(User).filter(User.id == uid).first()
            if not user or not user.notif_activity:
                continue
            locale = user.preferred_locale or "en"
            _send_to_user(
                user,
                title=_t(locale, "new_event_title", organization_name=organization_name),
                body=_t(locale, "new_event_body", event_title=event_title),
                data={"type": "new_event", "event_id": str(event_id)},
                db=db,
            )
        except Exception as exc:
            logger.error("push_new_event_failed | user_id=%s | error=%s", uid, exc)
