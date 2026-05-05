from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.core.auth import get_current_user
from app.models.notification import Notification
from app.models.organization_user import OrganizationUser
from app.models.user import User
from sqlalchemy import or_

router = APIRouter(prefix="/notifications", tags=["notifications"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def get_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    user_notifications = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
    )

    org_notifications = (
        db.query(Notification)
        .outerjoin(
            OrganizationUser,
            OrganizationUser.organization_id == Notification.organization_id
        )
        .filter(OrganizationUser.user_id == current_user.id)
    )

    notifications = (
        user_notifications.union(org_notifications)
        .order_by(Notification.created_at.desc())
        .all()
    )

    return notifications

@router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    notification = (
        db.query(Notification)
        .outerjoin(
            OrganizationUser,
            OrganizationUser.organization_id == Notification.organization_id
        )
        .filter(Notification.id == notification_id)
        .filter(
            or_(
                Notification.user_id == current_user.id,
                OrganizationUser.user_id == current_user.id
            )
        )
        .first()
    )

    if not notification:
        return {"error": "notification not found"}

    notification.is_read = True
    db.commit()

    return {"status": "ok"}

@router.get("/unread-count")
def get_unread_notifications_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    count = (
        db.query(Notification)
        .outerjoin(
            OrganizationUser,
            OrganizationUser.organization_id == Notification.organization_id
        )
        .filter(
            or_(
                Notification.user_id == current_user.id,
                OrganizationUser.user_id == current_user.id
            )
        )
        .filter(Notification.is_read == False)
        .count()
    )

    return {"count": count}

@router.post("/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    notifications = (
        db.query(Notification)
        .outerjoin(
            OrganizationUser,
            OrganizationUser.organization_id == Notification.organization_id
        )
        .filter(
            or_(
                Notification.user_id == current_user.id,
                OrganizationUser.user_id == current_user.id
            )
        )
        .all()
    )

    for n in notifications:
        n.is_read = True

    db.commit()

    return {"status": "ok"}