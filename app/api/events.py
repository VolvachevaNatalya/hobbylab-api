from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.dependencies import get_db
from app.models.event import Event
from app.schemas.event import EventCreate, EventResponse, EventUpdate
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.core.auth import get_current_user
from app.services.geocoding import geocode

router = APIRouter(
    prefix="/events",
    tags=["events"]
)


@router.get("/", response_model=List[EventResponse])
def get_events(organization_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Event)
    if organization_id is not None:
        query = query.filter(Event.organization_id == organization_id)
    return query.all()


@router.post("/", response_model=EventResponse)
def create_event(
    event: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    org_user = db.query(OrganizationUser).filter(OrganizationUser.organization_id == event.organization_id,
                                                 OrganizationUser.user_id == current_user.id).first()
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
def get_event(
    event_id: int,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(Event.id == event_id).first()

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return event

@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int,
    event_update: EventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == event.organization_id,
        OrganizationUser.user_id == current_user.id
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
    current_user: User = Depends(get_current_user)
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == event.organization_id,
        OrganizationUser.user_id == current_user.id
    ).first()

    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")
    db.delete(event)
    db.commit()

    return {"message": "Event deleted"}