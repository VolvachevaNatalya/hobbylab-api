import json
from typing import Set

from sqlalchemy.orm import Session

from app.models.favorite import Favorite
from app.models.notification import Notification
from app.models.organization_user import OrganizationUser

MEANINGFUL_UPDATE_FIELDS = frozenset({
    "title", "description", "start_datetime", "end_datetime",
    "address", "city", "city_id", "price", "price_comment",
    "min_age", "max_age", "capacity", "is_nationwide",
})


def has_meaningful_change(event, update_data: dict) -> bool:
    for field in MEANINGFUL_UPDATE_FIELDS:
        if field in update_data:
            if getattr(event, field, None) != update_data[field]:
                return True
    return False


def _event_favoriters(event_id: int, db: Session) -> Set[int]:
    return {
        r.user_id
        for r in db.query(Favorite.user_id)
        .filter(Favorite.entity_type == "event", Favorite.entity_id == event_id)
        .all()
    }


def _org_favoriters(org_id: int, db: Session) -> Set[int]:
    return {
        r.user_id
        for r in db.query(Favorite.user_id)
        .filter(Favorite.entity_type == "organization", Favorite.entity_id == org_id)
        .all()
    }


def _org_owner_ids(org_id: int, db: Session) -> Set[int]:
    return {
        r.user_id
        for r in db.query(OrganizationUser.user_id)
        .filter(
            OrganizationUser.organization_id == org_id,
            OrganizationUser.role == "owner",
        )
        .all()
    }


def _bulk_create(
    user_ids: Set[int],
    notif_type: str,
    title_key: str,
    body_key: str,
    payload: dict,
    db: Session,
) -> None:
    for uid in user_ids:
        db.add(Notification(
            user_id=uid,
            type=notif_type,
            title=title_key,
            message=body_key,
            payload=json.dumps(payload, ensure_ascii=False),
        ))


def notify_event_updated(event_id: int, event_title: str, actor_id: int, db: Session) -> None:
    recipients = _event_favoriters(event_id, db) - {actor_id}
    if not recipients:
        return
    _bulk_create(
        recipients,
        "event_updated",
        "notification.event_updated.title",
        "notification.event_updated.body",
        {"event_id": event_id, "event_title": event_title},
        db,
    )


def notify_event_cancelled(event_id: int, event_title: str, actor_id: int, db: Session) -> None:
    recipients = _event_favoriters(event_id, db) - {actor_id}
    if not recipients:
        return
    _bulk_create(
        recipients,
        "event_cancelled",
        "notification.event_cancelled.title",
        "notification.event_cancelled.body",
        {"event_id": event_id, "event_title": event_title},
        db,
    )


def notify_new_event(
    event_id: int,
    event_title: str,
    org_id: int,
    org_name: str,
    actor_id: int,
    db: Session,
) -> None:
    owners = _org_owner_ids(org_id, db)
    exclude = {actor_id} | owners
    recipients = _org_favoriters(org_id, db) - exclude
    if not recipients:
        return
    _bulk_create(
        recipients,
        "new_event",
        "notification.new_event.title",
        "notification.new_event.body",
        {"event_id": event_id, "event_title": event_title, "organization_name": org_name},
        db,
    )
