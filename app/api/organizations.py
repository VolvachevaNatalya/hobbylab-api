from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, exists, func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.classes import Class
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.organization_user import OrganizationUser
from app.models.promotion import Promotion
from app.models.review import Review
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationResponse, OrganizationUpdate
from app.services.geocoding import geocode

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _haversine(lat: float, lng: float, lat_col, lng_col):
    """SQLAlchemy expression for Haversine distance in km."""
    return 6371 * func.acos(
        func.least(
            1.0,
            func.cos(func.radians(lat)) * func.cos(func.radians(lat_col)) *
            func.cos(func.radians(lng_col) - func.radians(lng)) +
            func.sin(func.radians(lat)) * func.sin(func.radians(lat_col)),
        )
    )


def _promo_rank(promotion_type_col):
    """SQLAlchemy CASE expression mapping promotion_type to a sort rank."""
    return case(
        (promotion_type_col == "top", 3),
        (promotion_type_col == "featured", 2),
        (promotion_type_col == "highlighted", 1),
        else_=0,
    )


def _category_filter(category_id: Optional[int]):
    """EXISTS subquery: org has at least one class in the given category."""
    if category_id is None:
        return None
    return exists().where(
        (Class.organization_id == Organization.id) &
        (Class.category_id == category_id)
    )


def _rating_map(org_ids: list[int], db: Session) -> dict[int, tuple[float, int]]:
    """Returns {org_id: (average_rating, review_count)} for active reviews."""
    if not org_ids:
        return {}
    rows = (
        db.query(
            Review.organization_id,
            func.avg(Review.rating).label("avg"),
            func.count(Review.id).label("cnt"),
        )
        .filter(Review.organization_id.in_(org_ids), Review.status == "active")
        .group_by(Review.organization_id)
        .all()
    )
    return {r.organization_id: (round(float(r.avg), 2), int(r.cnt)) for r in rows}


@router.get("/", response_model=List[OrganizationResponse])
def get_organizations(
    user_latitude: Optional[float] = None,
    user_longitude: Optional[float] = None,
    radius_km: float = 25,
    category_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    cat_filter = _category_filter(category_id)

    if user_latitude is not None and user_longitude is not None:
        now = datetime.utcnow()
        dist = _haversine(user_latitude, user_longitude,
                          Organization.latitude, Organization.longitude)
        best_rank = func.coalesce(func.max(_promo_rank(Promotion.promotion_type)), 0)

        filters = [
            Organization.status == "active",
            Organization.verified == True,
            Organization.latitude.isnot(None),
            Organization.longitude.isnot(None),
            dist <= radius_km,
        ]
        if cat_filter is not None:
            filters.append(cat_filter)

        rows = (
            db.query(Organization, dist.label("dist_km"), best_rank.label("rank"))
            .outerjoin(
                Promotion,
                (Promotion.organization_id == Organization.id) &
                (Promotion.start_date <= now) &
                (Promotion.end_date >= now),
            )
            .filter(*filters)
            .group_by(Organization.id)
            .order_by(best_rank.desc(), dist.asc())
            .all()
        )

        ratings = _rating_map([org.id for org, _, _ in rows], db)
        out = []
        for org, dist_km, _ in rows:
            avg, cnt = ratings.get(org.id, (0.0, 0))
            resp = OrganizationResponse.model_validate(org)
            resp = resp.model_copy(update={
                "distance_km": round(float(dist_km), 2),
                "average_rating": avg,
                "review_count": cnt,
            })
            out.append(resp)
        return out

    # No radius — filter by category only
    base_filters = [Organization.status == "active", Organization.verified == True]
    if cat_filter is not None:
        base_filters.append(cat_filter)
    orgs = (
        db.query(Organization)
        .filter(*base_filters)
        .all()
    )
    ratings = _rating_map([o.id for o in orgs], db)
    out = []
    for org in orgs:
        avg, cnt = ratings.get(org.id, (0.0, 0))
        resp = OrganizationResponse.model_validate(org)
        resp = resp.model_copy(update={"average_rating": avg, "review_count": cnt})
        out.append(resp)
    return out


@router.post("/", response_model=OrganizationResponse)
def create_organization(
    org: OrganizationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_data = org.model_dump()
    lat, lng = geocode(org_data.get("address"), org_data.get("city"))
    if lat is not None:
        org_data["latitude"] = lat
        org_data["longitude"] = lng
    organization = Organization(**org_data, status="pending", verified=False)
    db.add(organization)
    db.flush()

    org_user = OrganizationUser(
        organization_id=organization.id,
        user_id=current_user.id,
        role="owner",
    )
    db.add(org_user)

    admin_notification = Notification(
        user_id=1,
        organization_id=organization.id,
        title="New organization pending approval",
        message=f"New organization pending approval: {organization.name}",
        type="new_organization",
    )
    db.add(admin_notification)

    db.commit()
    db.refresh(organization)
    return organization


@router.get("/my", response_model=List[OrganizationResponse])
def get_my_organizations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Organization)
        .join(OrganizationUser, Organization.id == OrganizationUser.organization_id)
        .filter(OrganizationUser.user_id == current_user.id)
        .all()
    )


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(organization_id: int, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.put("/{organization_id}", response_model=OrganizationResponse)
def update_organization(
    organization_id: int,
    org_update: OrganizationUpdate,
    db: Session = Depends(get_db),
):
    organization = db.query(Organization).filter(Organization.id == organization_id).first()
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    update_data = org_update.model_dump(exclude_unset=True)

    if "address" in update_data or "city" in update_data:
        new_address = update_data.get("address", organization.address)
        new_city = update_data.get("city", organization.city)
        lat, lng = geocode(new_address, new_city)
        if lat is not None:
            update_data["latitude"] = lat
            update_data["longitude"] = lng

    for key, value in update_data.items():
        setattr(organization, key, value)

    db.commit()
    db.refresh(organization)
    return organization


@router.delete("/{organization_id}")
def delete_organization(
    organization_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization = db.query(Organization).filter(Organization.id == organization_id).first()
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    membership = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == organization_id,
        OrganizationUser.user_id == current_user.id,
        OrganizationUser.role == "owner",
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Only the organization owner can delete it")

    # Explicitly remove records whose FKs have no ON DELETE CASCADE, in safe order.
    # payments must go before subscriptions (payment.subscription_id has no cascade).
    db.query(Payment).filter(Payment.organization_id == organization_id).delete()
    # promotions reference events (no cascade on event_id); delete before org cascades events.
    db.query(Promotion).filter(Promotion.organization_id == organization_id).delete()
    db.query(Subscription).filter(Subscription.organization_id == organization_id).delete()
    db.query(Notification).filter(Notification.organization_id == organization_id).delete()

    db.delete(organization)
    db.commit()
    return {"message": "Organization deleted"}
