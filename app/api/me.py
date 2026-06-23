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
    return current_user