from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.dependencies import get_db
from app.models.event import Event
from app.schemas.event import EventCreate, EventResponse, EventUpdate
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.core.auth import get_current_user

router = APIRouter(
    prefix="/events",
    tags=["events"]
)


@router.get("/", response_model=List[EventResponse])
def get_events(db: Session = Depends(get_db)):
    return db.query(Event).all()


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
    new_event = Event(**event.model_dump())


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

    for key, value in event_update.model_dump(exclude_unset=True).items():
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