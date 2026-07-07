from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, case, exists, func, or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.category import Category
from app.models.city import City
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.promotion import Promotion
from app.models.user import User
from app.schemas.category import CategoryResponse
from app.schemas.event import EventCreate, EventResponse, EventUpdate
from app.services.geocoding import geocode

router = APIRouter(prefix="/events", tags=["events"])


def _validate_city_id(city_id: Optional[int], db: Session) -> Optional[str]:
    if city_id is None:
        return None
    city = db.query(City).filter(City.id == city_id, City.is_active == True).first()
    if not city:
        raise HTTPException(status_code=400, detail=f"City id={city_id} not found")
    return city.name_en


def _city_map(city_ids, db: Session) -> dict:
    ids = [cid for cid in city_ids if cid is not None]
    if not ids:
        return {}
    cities = db.query(City).filter(City.id.in_(ids)).all()
    return {c.id: c for c in cities}


def _city_fields(city) -> dict:
    if city is None:
        return {"city_name_he": None, "city_name_en": None, "city_name_ru": None}
    return {"city_name_he": city.name_he, "city_name_en": city.name_en, "city_name_ru": city.name_ru}


def _enrich(event: Event, db: Session, city_map: Optional[dict] = None) -> EventResponse:
    """Build EventResponse and populate organization_name, categories, city fields, and backward-compat fields."""
    resp = EventResponse.model_validate(event)

    if event.organization_id:
        org = db.query(Organization.name).filter(
            Organization.id == event.organization_id
        ).scalar()
        resp = resp.model_copy(update={"organization_name": org})

    cat_rows = (
        db.query(Category)
        .join(EventCategory, EventCategory.category_id == Category.id)
        .filter(EventCategory.event_id == event.id)
        .order_by(EventCategory.position.asc(), Category.id.asc())
        .all()
    )

    if cat_rows:
        categories = [CategoryResponse.model_validate(c) for c in cat_rows]
        resp = resp.model_copy(update={
            "categories": categories,
            "category_id": cat_rows[0].id,
            "category_name": cat_rows[0].name,
        })
    elif event.category_id:
        # Fallback for events not yet backfilled into event_categories
        cat = db.query(Category).filter(Category.id == event.category_id).first()
        if cat:
            resp = resp.model_copy(update={
                "categories": [CategoryResponse.model_validate(cat)],
                "category_name": cat.name,
            })

    if event.city_id is not None:
        if city_map is not None:
            city = city_map.get(event.city_id)
        else:
            city = db.query(City).filter(City.id == event.city_id).first()
        resp = resp.model_copy(update=_city_fields(city))
    else:
        resp = resp.model_copy(update=_city_fields(None))

    return resp


def _validate_category_ids(category_ids: List[int], db: Session) -> None:
    existing_ids = {
        row.id for row in
        db.query(Category.id).filter(Category.id.in_(category_ids)).all()
    }
    missing = [cid for cid in category_ids if cid not in existing_ids]
    if missing:
        raise HTTPException(status_code=400, detail=f"Categories not found: {missing}")


def _category_filter(category_id: Optional[int]):
    """WHERE condition matching events that carry the given category.

    Checks both the legacy events.category_id column (old single-category events)
    and the event_categories junction table (multi-category events).  Using an
    EXISTS subquery instead of a JOIN means the event row is never multiplied, so
    no DISTINCT or extra GROUP BY is needed.
    """
    if category_id is None:
        return None
    return or_(
        Event.category_id == category_id,
        exists().where(
            (EventCategory.event_id == Event.id) &
            (EventCategory.category_id == category_id)
        ),
    )


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
    category_id: Optional[int] = None,
    city_id: Optional[int] = None,
    user_latitude: Optional[float] = None,
    user_longitude: Optional[float] = None,
    radius_km: float = 25,
    db: Session = Depends(get_db),
):
    cat_filter = _category_filter(category_id)

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
        if cat_filter is not None:
            query = query.filter(cat_filter)
        if city_id is not None:
            query = query.filter(Event.city_id == city_id)

        rows = query.all()
        cities = _city_map([ev.city_id for ev, _, _ in rows], db)
        out = []
        for event, dist_km, _ in rows:
            resp = _enrich(event, db, city_map=cities)
            resp = resp.model_copy(update={
                "distance_km": round(float(dist_km), 2) if dist_km is not None else None
            })
            out.append(resp)
        return out

    query = db.query(Event)
    if organization_id is not None:
        query = query.filter(Event.organization_id == organization_id)
    if cat_filter is not None:
        query = query.filter(cat_filter)
    if city_id is not None:
        query = query.filter(Event.city_id == city_id)
    events = query.all()
    cities = _city_map([ev.city_id for ev in events], db)
    return [_enrich(e, db, city_map=cities) for e in events]


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
    category_ids = event_data.pop("category_ids")

    _validate_category_ids(category_ids, db)
    city_name_en = _validate_city_id(event_data.get("city_id"), db)

    # Keep legacy column as first category for backward compatibility
    event_data["category_id"] = category_ids[0]

    geocode_city = event_data.get("city") or city_name_en
    lat, lng = geocode(event_data.get("address"), geocode_city)
    if lat is not None:
        event_data["latitude"] = lat
        event_data["longitude"] = lng

    new_event = Event(**event_data)
    db.add(new_event)
    db.flush()  # populate new_event.id before inserting junction rows

    for pos, cat_id in enumerate(category_ids):
        db.add(EventCategory(event_id=new_event.id, category_id=cat_id, position=pos))

    db.commit()
    db.refresh(new_event)
    return _enrich(new_event, db)


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

    # Pop category_ids — it is not a column on Event and must be handled separately
    category_ids = update_data.pop("category_ids", None)

    if category_ids is not None:
        _validate_category_ids(category_ids, db)

        db.query(EventCategory).filter(EventCategory.event_id == event_id).delete()
        for pos, cat_id in enumerate(category_ids):
            db.add(EventCategory(event_id=event_id, category_id=cat_id, position=pos))

        # Keep legacy column in sync
        update_data["category_id"] = category_ids[0]

    if "city_id" in update_data:
        _validate_city_id(update_data["city_id"], db)

    if "address" in update_data or "city" in update_data or "city_id" in update_data:
        new_address = update_data.get("address", event.address)
        new_city_id = update_data.get("city_id", event.city_id)
        new_city = update_data.get("city", event.city)
        if new_city is None and new_city_id is not None:
            city_obj = db.query(City).filter(City.id == new_city_id).first()
            new_city = city_obj.name_en if city_obj else None
        lat, lng = geocode(new_address, new_city)
        if lat is not None:
            update_data["latitude"] = lat
            update_data["longitude"] = lng

    for key, value in update_data.items():
        setattr(event, key, value)

    db.commit()
    db.refresh(event)
    return _enrich(event, db)


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
