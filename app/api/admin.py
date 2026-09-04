import io
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.auth import require_system_admin
from app.db.dependencies import get_db
from app.models.category import Category
from app.models.classes import Class
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.organization import Organization
from app.models.organization_category import OrganizationCategory
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.schemas.category import AdminCategoryUpdate, CategoryCreate
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


@router.get("/events")
def admin_list_events(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    total = db.query(func.count(Event.id)).scalar()
    events = (
        db.query(Event)
        .order_by(Event.created_at.desc(), Event.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Bulk org names — one query for all distinct orgs on this page.
    org_ids = list({e.organization_id for e in events if e.organization_id})
    org_name_map: dict = {}
    if org_ids:
        rows = (
            db.query(Organization.id, Organization.name)
            .filter(Organization.id.in_(org_ids))
            .all()
        )
        org_name_map = {r.id: r.name for r in rows}

    # Bulk categories — one query for all events on this page.
    event_ids = [e.id for e in events]
    cat_rows = (
        db.query(
            EventCategory.event_id,
            Category.id.label("cat_id"),
            Category.name,
            Category.name_en,
            Category.name_ru,
            Category.name_he,
        )
        .join(Category, Category.id == EventCategory.category_id)
        .filter(EventCategory.event_id.in_(event_ids))
        .order_by(EventCategory.event_id, EventCategory.position)
        .all()
    ) if event_ids else []

    cats_by_event: dict = {}
    for row in cat_rows:
        cats_by_event.setdefault(row.event_id, []).append({
            "id":      row.cat_id,
            "name":    row.name,
            "name_en": row.name_en,
            "name_ru": row.name_ru,
            "name_he": row.name_he,
        })

    return {
        "items": [
            {
                "id":                e.id,
                "title":             e.title,
                "status":            e.status,
                "start_datetime":    e.start_datetime,
                "end_datetime":      e.end_datetime,
                "created_at":        e.created_at,
                "city":              e.city,
                "city_id":           e.city_id,
                "price":             float(e.price) if e.price is not None else None,
                "is_nationwide":     e.is_nationwide,
                "series_id":         e.series_id,
                "organization_id":   e.organization_id,
                "organization_name": org_name_map.get(e.organization_id),
                "categories":        cats_by_event.get(e.id, []),
            }
            for e in events
        ],
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


def _category_dict(c: Category) -> dict:
    return {
        "id":       c.id,
        "name":     c.name,
        "name_en":  c.name_en,
        "name_ru":  c.name_ru,
        "name_he":  c.name_he,
        "icon_url": c.icon_url,
    }


@router.get("/categories")
def admin_list_categories(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    total = db.query(func.count(Category.id)).scalar()
    categories = (
        db.query(Category)
        .order_by(Category.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id":      c.id,
                "name":    c.name,
                "name_en": c.name_en,
                "name_ru": c.name_ru,
                "name_he": c.name_he,
                "icon_url": c.icon_url,
            }
            for c in categories
        ],
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


@router.post("/categories")
def admin_create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
):
    category = Category(**payload.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return _category_dict(category)


@router.patch("/categories/{category_id}")
def admin_update_category(
    category_id: int,
    payload: AdminCategoryUpdate,
    db: Session = Depends(get_db),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, key, value)
    db.commit()
    db.refresh(category)
    return _category_dict(category)


@router.delete("/categories/{category_id}")
def admin_delete_category(
    category_id: int,
    db: Session = Depends(get_db),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # events.category_id and classes.category_id have no ondelete clause,
    # so PostgreSQL would RESTRICT the delete. Reject explicitly here so
    # the 409 is clear and consistent across all DB backends.
    in_use = (
        db.query(func.count(EventCategory.event_id))
        .filter(EventCategory.category_id == category_id)
        .scalar() > 0
        or
        db.query(func.count(Event.id))
        .filter(Event.category_id == category_id)
        .scalar() > 0
        or
        db.query(func.count(Class.id))
        .filter(Class.category_id == category_id)
        .scalar() > 0
    )
    if in_use:
        raise HTTPException(
            status_code=409,
            detail="Category is in use by events or classes and cannot be deleted",
        )

    # OrganizationCategory has ondelete=CASCADE in PostgreSQL, but SQLite does
    # not enforce FK constraints, so delete the junction rows explicitly.
    db.query(OrganizationCategory).filter(
        OrganizationCategory.category_id == category_id
    ).delete(synchronize_session=False)

    db.delete(category)
    db.commit()
    return {"message": "Category deleted"}


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
