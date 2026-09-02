import io
import os

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.auth import require_system_admin
from app.db.dependencies import get_db
from app.models.event import Event
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.services.geocoding import geocode

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_system_admin)],
)


@router.get("/me")
def admin_me(current_user: User = Depends(require_system_admin)):
    return {
        "id":    current_user.id,
        "email": current_user.email,
        "name":  current_user.name,
    }


@router.get("/users")
def admin_list_users(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    total = db.query(func.count(User.id)).scalar()
    users = (
        db.query(User)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id":             u.id,
                "name":           u.name,
                "email":          u.email,
                "provider":       u.provider,
                "status":         u.status,
                "is_system_admin": u.is_system_admin,
                "created_at":     u.created_at,
            }
            for u in users
        ],
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


@router.get("/organizations")
def admin_list_organizations(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    total = db.query(func.count(Organization.id)).scalar()
    orgs = (
        db.query(Organization)
        .order_by(Organization.created_at.desc(), Organization.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Fetch all org members for this page in one query — no N+1.
    org_ids = [o.id for o in orgs]
    member_rows = (
        db.query(
            OrganizationUser.organization_id,
            OrganizationUser.role,
            User.id.label("user_id"),
            User.name.label("user_name"),
            User.email.label("user_email"),
        )
        .join(User, User.id == OrganizationUser.user_id)
        .filter(OrganizationUser.organization_id.in_(org_ids))
        .all()
    ) if org_ids else []

    users_by_org: dict = {}
    for row in member_rows:
        users_by_org.setdefault(row.organization_id, []).append({
            "id":    row.user_id,
            "name":  row.user_name,
            "email": row.user_email,
            "role":  row.role,
        })

    return {
        "items": [
            {
                "id":         o.id,
                "name":       o.name,
                "email":      o.email,
                "phone":      o.phone,
                "city":       o.city,
                "city_id":    o.city_id,
                "status":     o.status,
                "verified":   o.verified,
                "created_at": o.created_at,
                "users":      users_by_org.get(o.id, []),
            }
            for o in orgs
        ],
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


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
