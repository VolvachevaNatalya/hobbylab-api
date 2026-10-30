from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_system_admin
from app.core.org_permissions import get_membership
from app.db.dependencies import get_db
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.subscription import SubscriptionCreate, SubscriptionUpdate


router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/organization/{organization_id}")
def get_subscription(
    organization_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_system_admin:
        if not get_membership(organization_id, current_user.id, db):
            raise HTTPException(status_code=403, detail="Not authorized")

    subscription = (
        db.query(Subscription)
        .filter(Subscription.organization_id == organization_id)
        .first()
    )

    if not subscription:
        return {"subscription": None}

    return subscription


@router.post("/")
def create_subscription(
    data: SubscriptionCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_system_admin),
):
    existing = (
        db.query(Subscription)
        .filter(Subscription.organization_id == data.organization_id)
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="subscription already exists")

    subscription = Subscription(**data.dict())
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


@router.put("/{subscription_id}")
def update_subscription(
    subscription_id: int,
    data: SubscriptionUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_system_admin),
):
    subscription = (
        db.query(Subscription)
        .filter(Subscription.id == subscription_id)
        .first()
    )

    if not subscription:
        raise HTTPException(status_code=404, detail="subscription not found")

    for key, value in data.dict(exclude_unset=True).items():
        setattr(subscription, key, value)

    db.commit()
    db.refresh(subscription)
    return subscription


@router.delete("/{subscription_id}")
def delete_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_system_admin),
):
    subscription = (
        db.query(Subscription)
        .filter(Subscription.id == subscription_id)
        .first()
    )

    if not subscription:
        raise HTTPException(status_code=404, detail="subscription not found")

    db.delete(subscription)
    db.commit()
    return {"status": "deleted"}
