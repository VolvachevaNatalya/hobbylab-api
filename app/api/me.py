from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.device_token import DeviceToken
from app.models.user import User
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user_auth_provider import UserAuthProvider

_VALID_LOCALES = frozenset({"en", "ru", "he"})

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


class DeviceTokenRequest(BaseModel):
    token: str
    platform: str = "android"


class LocaleRequest(BaseModel):
    locale: str


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


@router.post("/me/device-token", status_code=200)
def register_device_token(
    body: DeviceTokenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register or refresh an FCM device token for the authenticated user.

    If the token is already associated with a different account (e.g. after an
    account switch on the same device) it is re-assigned to the current user.
    """
    if not body.token or not body.token.strip():
        raise HTTPException(status_code=400, detail="Token must not be empty")

    existing = db.query(DeviceToken).filter(DeviceToken.token == body.token).first()
    if existing:
        if existing.user_id != current_user.id:
            # Token belonged to a previous account on this device — reassign it
            existing.user_id = current_user.id
            existing.platform = body.platform
            db.commit()
        return {"status": "ok"}

    db.add(DeviceToken(
        user_id=current_user.id,
        token=body.token,
        platform=body.platform,
    ))
    db.commit()
    return {"status": "ok"}


@router.delete("/me/device-token", status_code=200)
def remove_device_token(
    body: DeviceTokenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove an FCM device token on logout or account switch."""
    db.query(DeviceToken).filter(
        DeviceToken.token == body.token,
        DeviceToken.user_id == current_user.id,
    ).delete()
    db.commit()
    return {"status": "ok"}


@router.put("/me/locale", status_code=200)
def update_locale(
    body: LocaleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sync the user's preferred locale for localized push notification text."""
    if body.locale not in _VALID_LOCALES:
        raise HTTPException(status_code=400, detail=f"locale must be one of {sorted(_VALID_LOCALES)}")
    current_user.preferred_locale = body.locale
    db.commit()
    return {"locale": body.locale}


@router.delete("/me", status_code=204)
def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Already deleted — idempotent
    if current_user.status == "deleted":
        return Response(status_code=204)

    # Refuse if user is the sole owner of any organisation
    owned_memberships = (
        db.query(OrganizationUser)
        .filter(OrganizationUser.user_id == current_user.id, OrganizationUser.role == "owner")
        .all()
    )
    for membership in owned_memberships:
        other_owners = (
            db.query(OrganizationUser)
            .filter(
                OrganizationUser.organization_id == membership.organization_id,
                OrganizationUser.role == "owner",
                OrganizationUser.user_id != current_user.id,
            )
            .count()
        )
        if other_owners == 0:
            org = db.query(Organization).filter(Organization.id == membership.organization_id).first()
            name = org.name if org else f"organization #{membership.organization_id}"
            raise HTTPException(
                status_code=409,
                detail=f"You are the sole owner of '{name}'. Transfer ownership or delete the organization first.",
            )

    # Bump token_version → invalidates all existing JWTs / refresh tokens immediately
    current_user.token_version = (current_user.token_version or 0) + 1

    # Soft-delete: blocks all future auth paths without destroying shared data
    current_user.status = "deleted"

    # Anonymize the email so the address is immediately available for a fresh
    # registration with the same social identity.  The soft-deleted row's data
    # (reviews, messages, etc.) is preserved; only the email is replaced.
    current_user.email = f"deleted_{current_user.id}@deleted.local"

    # Remove provider links → prevents re-login restoring the deleted account
    db.query(UserAuthProvider).filter(UserAuthProvider.user_id == current_user.id).delete()

    # Remove device tokens → deleted accounts must not receive push notifications
    db.query(DeviceToken).filter(DeviceToken.user_id == current_user.id).delete()

    db.commit()
    return Response(status_code=204)