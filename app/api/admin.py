import io
import os

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.event import Event
from app.models.organization import Organization
from app.services.geocoding import geocode

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/test-webdav")
def test_webdav():
    from webdav3.client import Client

    _PUBLIC_BASE = "https://static.hobbylab.co.il"
    webdav_url = os.getenv("WEBDAV_URL", "davs://static.hobbylab.co.il/upload")
    username = os.getenv("WEBDAV_USERNAME", "")
    password = os.getenv("WEBDAV_PASSWORD", "")

    webdav_host = webdav_url.replace("davs://", "https://").replace("dav://", "http://")

    masked_url = webdav_host
    if password:
        masked_url = webdav_host.replace(password, "***")

    client = Client({
        "webdav_hostname": webdav_host,
        "webdav_login": username,
        "webdav_password": password,
    })

    check_result: bool | str
    try:
        check_result = client.check("/")
    except Exception as e:
        check_result = str(e)

    remote_filename = "test_railway.txt"
    upload_result: str
    try:
        client.upload_to(buff=io.BytesIO(b"hello webdav test from Railway"), remote_path=remote_filename)
        upload_result = "success"
    except Exception as e:
        upload_result = str(e)

    return {
        "webdav_url": masked_url,
        "webdav_username": username,
        "check_result": check_result,
        "upload_result": upload_result,
        "public_url": f"{_PUBLIC_BASE}/{remote_filename}",
    }


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
