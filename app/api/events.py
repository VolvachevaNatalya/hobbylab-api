from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.category import Category
from app.models.event import Event
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.promotion import Promotion
from app.models.user import User
from app.schemas.event import EventCreate, EventResponse, EventUpdate
from app.services.geocoding import geocode

router = APIRouter(prefix="/events", tags=["events"])


def _enrich(event: Event, db: Session) -> EventResponse:
    """Build EventResponse and populate joined organization_name / category_name."""
    resp = EventResponse.model_validate(event)
    if event.organization_id:
        org = db.query(Organization.name).filter(
            Organization.id == event.organization_id
        ).scalar()
        resp = resp.model_copy(update={"organization_name": org})
    if event.category_id:
        cat = db.query(Category.name).filter(
            Category.id == event.category_id
        ).scalar()
        resp = resp.model_copy(update={"category_name": cat})
    return resp


def _haversine(lat: float, lng: float, lat_col, lng_col):
    return 6371 * func.acos(
        func.least(
            1.0,
            func.cos(func.radians(lat)) * func.cos(func.radians(lat_col)) *
            func.cos(func.radians(lng_col) - func.radians(lng)) +
            func.sin(func.radians(lat)) * func.sin(func.radians(lat_col)),
        )
    )


def _promo_rank(promotion_type_col):
    return case(
        (promotion_type_col == "top", 3),
        (promotion_type_col == "featured", 2),
        (promotion_type_col == "highlighted", 1),
        else_=0,
    )


@router.get("/", response_model=List[EventResponse])
def get_events(
    organization_id: Optional[int] = None,
    user_latitude: Optional[float] = None,
    user_longitude: Optional[float] = None,
    radius_km: float = 25,
    db: Session = Depends(get_db),
):
    if user_latitude is not None and user_longitude is not None:
        now = datetime.utcnow()
        dist = _haversine(user_latitude, user_longitude, Event.latitude, Event.longitude)
        best_rank = func.coalesce(func.max(_promo_rank(Promotion.promotion_type)), 0)

        query = (
            db.query(Event, dist.label("dist_km"), best_rank.label("rank"))
            .outerjoin(
                Promotion,
                (Promotion.event_id == Event.id) &
                (Promotion.start_date <= now) &
                (Promotion.end_date >= now),
            )
            .filter(
                or_(
                    Event.is_nationwide == True,
                    and_(
                        Event.latitude.isnot(None),
                        Event.longitude.isnot(None),
                        dist <= radius_km,
                    ),
                )
            )
            .group_by(Event.id)
            .order_by(best_rank.desc(), func.coalesce(dist, 9999.0).asc())
        )
        if organization_id is not None:
            query = query.filter(Event.organization_id == organization_id)

        out = []
        for event, dist_km, _ in query.all():
            resp = _enrich(event, db)
            resp = resp.model_copy(update={
                "distance_km": round(float(dist_km), 2) if dist_km is not None else None
            })
            out.append(resp)
        return out

    query = db.query(Event)
    if organization_id is not None:
        query = query.filter(Event.organization_id == organization_id)
    return [_enrich(e, db) for e in query.all()]


@router.post("/", response_model=EventResponse)
def create_event(
    event: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == event.organization_id,
        OrganizationUser.user_id == current_user.id,
    ).first()
    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")

    event_data = event.model_dump()
    lat, lng = geocode(event_data.get("address"), event_data.get("city"))
    if lat is not None:
        event_data["latitude"] = lat
        event_data["longitude"] = lng
    new_event = Event(**event_data)

    db.add(new_event)
    db.commit()
    db.refresh(new_event)
    return new_event


@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return _enrich(event, db)


@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int,
    event_update: EventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == event.organization_id,
        OrganizationUser.user_id == current_user.id,
    ).first()
    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")

    update_data = event_update.model_dump(exclude_unset=True)
    if "address" in update_data or "city" in update_data:
        new_address = update_data.get("address", event.address)
        new_city = update_data.get("city", event.city)
        lat, lng = geocode(new_address, new_city)
        if lat is not None:
            update_data["latitude"] = lat
            update_data["longitude"] = lng

    for key, value in update_data.items():
        setattr(event, key, value)

    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}")
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == event.organization_id,
        OrganizationUser.user_id == current_user.id,
    ).first()
    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")
    db.delete(event)
    db.commit()
    return {"message": "Event deleted"}
