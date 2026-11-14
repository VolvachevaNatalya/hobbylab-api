from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.user import User

router = APIRouter()


class UserUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None


class NotificationPreferencesResponse(BaseModel):
    notif_appointments: bool
    notif_chat: bool
    notif_activity: bool
    notif_offers: bool


class NotificationPreferencesUpdate(BaseModel):
    notif_appointments: Optional[bool] = None
    notif_chat: Optional[bool] = None
    notif_activity: Optional[bool] = None
    notif_offers: Optional[bool] = None


def _is_fallback_email(user: User) -> bool:
    return user.provider == "facebook" and (user.email or "").endswith("@facebook.local")


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": None if _is_fallback_email(current_user) else current_user.email,
        "name": current_user.name,
        "phone": current_user.phone,
        "avatar_url": current_user.avatar_url,
        "provider": current_user.provider,
        "provider_user_id": current_user.provider_user_id,
        "status": current_user.status,
        "created_at": current_user.created_at,
    }


@router.patch("/me")
def update_me(
    body: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.name is not None:
        current_user.name = body.name
    if body.phone is not None:
        current_user.phone = body.phone
    if body.avatar_url is not None:
        current_user.avatar_url = body.avatar_url
    db.commit()
    db.refresh(current_user)
    return {
        "id": current_user.id,
        "email": None if _is_fallback_email(current_user) else current_user.email,
        "name": current_user.name,
        "phone": current_user.phone,
        "avatar_url": current_user.avatar_url,
        "provider": current_user.provider,
        "provider_user_id": current_user.provider_user_id,
        "status": current_user.status,
        "created_at": current_user.created_at,
    }


@router.get("/me/notification-preferences", response_model=NotificationPreferencesResponse)
def get_notification_preferences(current_user: User = Depends(get_current_user)):
    return NotificationPreferencesResponse(
        notif_appointments=current_user.notif_appointments if current_user.notif_appointments is not None else True,
        notif_chat=current_user.notif_chat if current_user.notif_chat is not None else True,
        notif_activity=current_user.notif_activity if current_user.notif_activity is not None else False,
        notif_offers=current_user.notif_offers if current_user.notif_offers is not None else True,
    )


@router.put("/me/notification-preferences", response_model=NotificationPreferencesResponse)
def update_notification_preferences(
    body: NotificationPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.notif_appointments is not None:
        current_user.notif_appointments = body.notif_appointments
    if body.notif_chat is not None:
        current_user.notif_chat = body.notif_chat
    if body.notif_activity is not None:
        current_user.notif_activity = body.notif_activity
    if body.notif_offers is not None:
        current_user.notif_offers = body.notif_offers
    db.commit()
    db.refresh(current_user)
    return NotificationPreferencesResponse(
        notif_appointments=current_user.notif_appointments,
        notif_chat=current_user.notif_chat,
        notif_activity=current_user.notif_activity,
        notif_offers=current_user.notif_offers,
    )