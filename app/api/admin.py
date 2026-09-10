import io
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.events import _do_create_event, _do_delete_event, _do_update_event, _enrich
from app.api.organizations import (
    _category_map,
    _city_fields,
    _city_map,
    _validate_category_ids,
    _validate_city_id,
)
from app.core.auth import require_system_admin
from app.db.dependencies import get_db
from app.models.category import Category
from app.models.city import City
from app.models.classes import Class
from app.models.event import Event
from app.models.event_category import EventCategory
from app.models.event_series import EventSeries
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.organization_category import OrganizationCategory
from app.models.organization_user import OrganizationUser
from app.models.payment import Payment
from app.models.promotion import Promotion
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.category import AdminCategoryUpdate, CategoryCreate
from app.schemas.event import EventCreate, EventUpdate
from app.schemas.organization import AdminOrganizationCreate, AdminOrganizationUpdate
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


def _admin_org_dict(org: Organization, db: Session) -> dict:
    """Full organization representation for admin POST/PATCH responses."""
    users = (
        db.query(
            OrganizationUser.role,
            User.id.label("user_id"),
            User.name.label("user_name"),
            User.email.label("user_email"),
        )
        .join(User, User.id == OrganizationUser.user_id)
        .filter(OrganizationUser.organization_id == org.id)
        .all()
    )
    cats = _category_map([org.id], db).get(org.id, [])
    return {
        "id":           org.id,
        "name":         org.name,
        "description":  org.description,
        "logo_url":     org.logo_url,
        "banner_url":   org.banner_url,
        "email":        org.email,
        "phone":        org.phone,
        "website":      org.website,
        "instagram_url":  org.instagram_url,
        "facebook_url":   org.facebook_url,
        "telegram_url":   org.telegram_url,
        "youtube_url":    org.youtube_url,
        "tiktok_url":     org.tiktok_url,
        "whatsapp_url":   org.whatsapp_url,
        "address":        org.address,
        "city":           org.city,
        "city_id":        org.city_id,
        "latitude":       float(org.latitude) if org.latitude is not None else None,
        "longitude":      float(org.longitude) if org.longitude is not None else None,
        "trial_lesson_available": org.trial_lesson_available,
        "trial_lesson_price":     float(org.trial_lesson_price) if org.trial_lesson_price is not None else None,
        "trial_lesson_comment":   org.trial_lesson_comment,
        "status":     org.status,
        "verified":   org.verified,
        "created_at": org.created_at,
        "updated_at": org.updated_at,
        "users": [
            {"id": r.user_id, "name": r.user_name, "email": r.user_email, "role": r.role}
            for r in users
        ],
        "categories": [c.model_dump() for c in cats],
    }


@router.post("/organizations")
def admin_create_organization(
    payload: AdminOrganizationCreate,
    db: Session = Depends(get_db),
):
    data = payload.model_dump()
    category_ids = data.pop("category_ids")
    owner_id = data.pop("owner_id")

    if owner_id is not None:
        if not db.query(User).filter(User.id == owner_id).first():
            raise HTTPException(status_code=400, detail=f"User id={owner_id} not found")

    if category_ids is not None:
        _validate_category_ids(category_ids, db)

    city_name_en = _validate_city_id(data.get("city_id"), db)
    geocode_city = data.get("city") or city_name_en
    lat, lng = geocode(data.get("address"), geocode_city)
    if lat is not None:
        data["latitude"] = lat
        data["longitude"] = lng

    org = Organization(**data)
    db.add(org)
    db.flush()

    if owner_id is not None:
        db.add(OrganizationUser(
            organization_id=org.id,
            user_id=owner_id,
            role="owner",
        ))

    if category_ids is not None:
        for pos, cat_id in enumerate(category_ids):
            db.add(OrganizationCategory(
                organization_id=org.id,
                category_id=cat_id,
                position=pos,
            ))

    db.commit()
    db.refresh(org)
    return _admin_org_dict(org, db)


@router.get("/organizations/{organization_id}")
def admin_get_organization(
    organization_id: int,
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _admin_org_dict(org, db)


@router.patch("/organizations/{organization_id}")
def admin_update_organization(
    organization_id: int,
    payload: AdminOrganizationUpdate,
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    update_data = payload.model_dump(exclude_unset=True)
    category_ids = update_data.pop("category_ids", None)

    if category_ids is not None:
        _validate_category_ids(category_ids, db)
        db.query(OrganizationCategory).filter(
            OrganizationCategory.organization_id == organization_id
        ).delete()
        for pos, cat_id in enumerate(category_ids):
            db.add(OrganizationCategory(
                organization_id=organization_id,
                category_id=cat_id,
                position=pos,
            ))

    if "city_id" in update_data:
        _validate_city_id(update_data["city_id"], db)

    if "address" in update_data or "city" in update_data or "city_id" in update_data:
        new_address = update_data.get("address", org.address)
        new_city_id = update_data.get("city_id", org.city_id)
        new_city = update_data.get("city", org.city)
        if new_city is None and new_city_id is not None:
            city_obj = db.query(City).filter(City.id == new_city_id).first()
            new_city = city_obj.name_en if city_obj else None
        lat, lng = geocode(new_address, new_city)
        if lat is not None:
            update_data["latitude"] = lat
            update_data["longitude"] = lng

    for key, value in update_data.items():
        setattr(org, key, value)

    db.commit()
    db.refresh(org)
    return _admin_org_dict(org, db)


@router.delete("/organizations/{organization_id}")
def admin_delete_organization(
    organization_id: int,
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Replicate the safe deletion sequence from the existing mobile endpoint
    # (app/api/organizations.py::delete_organization). These four tables have
    # no ON DELETE CASCADE and must be cleared before the org row is removed.
    db.query(Payment).filter(Payment.organization_id == organization_id).delete()
    db.query(Promotion).filter(Promotion.organization_id == organization_id).delete()
    db.query(Subscription).filter(Subscription.organization_id == organization_id).delete()
    db.query(Notification).filter(Notification.organization_id == organization_id).delete()

    db.delete(org)
    db.commit()
    return {"message": "Organization deleted"}


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


@router.post("/events")
def admin_create_event(
    event: EventCreate,
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == event.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    recurrence = event.recurrence
    event_data = event.model_dump()
    category_ids = event_data.pop("category_ids")
    event_data.pop("recurrence", None)
    if isinstance(event_data.get("age_groups"), list):
        event_data["age_groups"] = json.dumps(event_data["age_groups"])

    new_event = _do_create_event(event_data, category_ids, recurrence, db)
    return _enrich(new_event, db)


@router.get("/events/{event_id}")
def admin_get_event(
    event_id: int,
    db: Session = Depends(get_db),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return _enrich(event, db)


@router.patch("/events/{event_id}")
def admin_update_event(
    event_id: int,
    event_update: EventUpdate,
    scope: str = "single",
    db: Session = Depends(get_db),
):
    if scope not in ("single", "future", "series"):
        raise HTTPException(status_code=400, detail="scope must be single, future, or series")

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    recurrence = event_update.recurrence
    remove_recurrence = (
        "recurrence" in event_update.model_fields_set and event_update.recurrence is None
    )
    update_data = event_update.model_dump(exclude_unset=True)
    category_ids = update_data.pop("category_ids", None)
    update_data.pop("recurrence", None)
    if isinstance(update_data.get("age_groups"), list):
        update_data["age_groups"] = json.dumps(update_data["age_groups"])

    return _do_update_event(event, update_data, category_ids, recurrence, remove_recurrence, scope, db)


@router.delete("/events/{event_id}")
def admin_delete_event(
    event_id: int,
    scope: str = "single",
    db: Session = Depends(get_db),
):
    if scope not in ("single", "future", "series"):
        raise HTTPException(status_code=400, detail="scope must be single, future, or series")

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return _do_delete_event(event, scope, db)


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
