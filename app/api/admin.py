from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.event import Event
from app.models.organization import Organization
from app.services.geocoding import geocode

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/geocode-existing")
def geocode_existing(db: Session = Depends(get_db)):
    """
    One-time backfill: geocode all organizations and events that have an
    address or city but are missing coordinates.
    """
    updated_orgs = 0
    updated_events = 0
    failed = 0

    orgs = (
        db.query(Organization)
        .filter(
            Organization.latitude.is_(None),
            or_(
                Organization.address.isnot(None),
                Organization.city.isnot(None),
            ),
        )
        .all()
    )

    for org in orgs:
        lat, lng = geocode(org.address, org.city)
        if lat is not None:
            org.latitude = lat
            org.longitude = lng
            updated_orgs += 1
        else:
            failed += 1

    events = (
        db.query(Event)
        .filter(
            Event.latitude.is_(None),
            or_(
                Event.address.isnot(None),
                Event.city.isnot(None),
            ),
        )
        .all()
    )

    for event in events:
        lat, lng = geocode(event.address, event.city)
        if lat is not None:
            event.latitude = lat
            event.longitude = lng
            updated_events += 1
        else:
            failed += 1

    db.commit()

    return {
        "updated_organizations": updated_orgs,
        "updated_events": updated_events,
        "failed": failed,
    }
