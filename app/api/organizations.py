from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.promotion import Promotion
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


@router.get("/", response_model=List[OrganizationResponse])
def get_organizations(
    user_latitude: Optional[float] = None,
    user_longitude: Optional[float] = None,
    radius_km: float = 25,
    db: Session = Depends(get_db),
):
    if user_latitude is not None and user_longitude is not None:
        now = datetime.utcnow()
        dist = _haversine(user_latitude, user_longitude,
                          Organization.latitude, Organization.longitude)
        best_rank = func.coalesce(func.max(_promo_rank(Promotion.promotion_type)), 0)

        rows = (
            db.query(Organization, dist.label("dist_km"), best_rank.label("rank"))
            .outerjoin(
                Promotion,
                (Promotion.organization_id == Organization.id) &
                (Promotion.start_date <= now) &
                (Promotion.end_date >= now),
            )
            .filter(
                Organization.status == "active",
                Organization.verified == True,
                Organization.latitude.isnot(None),
                Organization.longitude.isnot(None),
                dist <= radius_km,
            )
            .group_by(Organization.id)
            .order_by(best_rank.desc(), dist.asc())
            .all()
        )

        out = []
        for org, dist_km, _ in rows:
            resp = OrganizationResponse.model_validate(org)
            resp = resp.model_copy(update={"distance_km": round(float(dist_km), 2)})
            out.append(resp)
        return out

    return (
        db.query(Organization)
        .filter(Organization.status == "active", Organization.verified == True)
        .all()
    )


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
def delete_organization(organization_id: int, db: Session = Depends(get_db)):
    organization = db.query(Organization).filter(Organization.id == organization_id).first()
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    db.delete(organization)
    db.commit()
    return {"message": "Organization deleted"}
