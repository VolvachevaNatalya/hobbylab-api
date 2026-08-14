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
from app.models.event_series import EventSeries
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.promotion import Promotion
from app.models.user import User
from app.schemas.category import CategoryResponse
from app.schemas.event import EventCreate, EventResponse, EventUpdate
from app.schemas.event_series import RecurrenceCreate, RecurrenceResponse
from app.services.geocoding import geocode
from app.services.recurrence import adjust_original_series_after_split, generate_dates

router = APIRouter(prefix="/events", tags=["events"])

# ── Shared field names that can be bulk-applied across occurrences ─────────────
_SHARED_EVENT_FIELDS = frozenset({
    "title", "description", "min_age", "max_age", "capacity",
    "image_url", "banner_url", "address", "city", "city_id",
    "latitude", "longitude", "is_nationwide", "price", "price_comment", "status",
})


# ── Validation helpers ─────────────────────────────────────────────────────────

def _validate_city_id(city_id: Optional[int], db: Session) -> Optional[str]:
    if city_id is None:
        return None
    city = db.query(City).filter(City.id == city_id, City.is_active == True).first()
    if not city:
        raise HTTPException(status_code=400, detail=f"City id={city_id} not found")
    return city.name_en


def _validate_category_ids(category_ids: List[int], db: Session) -> None:
    existing_ids = {
        row.id for row in
        db.query(Category.id).filter(Category.id.in_(category_ids)).all()
    }
    missing = [cid for cid in category_ids if cid not in existing_ids]
    if missing:
        raise HTTPException(status_code=400, detail=f"Categories not found: {missing}")


# ── Query / read helpers ───────────────────────────────────────────────────────

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


def _series_map(series_ids, db: Session) -> dict:
    ids = [sid for sid in series_ids if sid is not None]
    if not ids:
        return {}
    rows = db.query(EventSeries).filter(EventSeries.id.in_(ids)).all()
    return {s.id: s for s in rows}


def _enrich(event: Event, db: Session, city_map: Optional[dict] = None, series_map: Optional[dict] = None) -> EventResponse:
    """Build EventResponse with organization_name, categories, city fields, and recurrence."""
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
        cat = db.query(Category).filter(Category.id == event.category_id).first()
        if cat:
            resp = resp.model_copy(update={
                "categories": [CategoryResponse.model_validate(cat)],
                "category_name": cat.name,
            })

    if event.city_id is not None:
        city = city_map.get(event.city_id) if city_map is not None else db.query(City).filter(City.id == event.city_id).first()
        resp = resp.model_copy(update=_city_fields(city))
    else:
        resp = resp.model_copy(update=_city_fields(None))

    if event.series_id is not None:
        if series_map is not None:
            series = series_map.get(event.series_id)
        else:
            series = db.query(EventSeries).filter(EventSeries.id == event.series_id).first()
        if series:
            resp = resp.model_copy(update={"recurrence": RecurrenceResponse.model_validate(series)})

    return resp


def _category_filter(category_id: Optional[int]):
    """WHERE condition matching events that carry the given category via either column."""
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


def _get_event_category_ids(event_id: int, event_category_id: Optional[int], db: Session) -> List[int]:
    """Return ordered category IDs for an event from the junction table, falling back to category_id."""
    rows = (
        db.query(EventCategory.category_id)
        .filter(EventCategory.event_id == event_id)
        .order_by(EventCategory.position)
        .all()
    )
    ids = [r.category_id for r in rows]
    if not ids and event_category_id:
        ids = [event_category_id]
    return ids


def _build_shared_fields(template: Event, overrides: dict) -> dict:
    """Build the per-row fields that are identical across all occurrences of a series."""
    return {
        "organization_id": template.organization_id,
        "title": overrides.get("title", template.title),
        "description": overrides.get("description", template.description),
        "min_age": overrides.get("min_age", template.min_age),
        "max_age": overrides.get("max_age", template.max_age),
        "capacity": overrides.get("capacity", template.capacity),
        "image_url": overrides.get("image_url", template.image_url),
        "banner_url": overrides.get("banner_url", template.banner_url),
        "address": overrides.get("address", template.address),
        "city": overrides.get("city", template.city),
        "city_id": overrides.get("city_id", template.city_id),
        "latitude": overrides.get("latitude", template.latitude),
        "longitude": overrides.get("longitude", template.longitude),
        "is_nationwide": overrides.get("is_nationwide", template.is_nationwide),
        "price": overrides.get("price", template.price),
        "price_comment": overrides.get("price_comment", template.price_comment),
        "status": overrides.get("status", template.status),
    }


def _compute_duration(template: Event, update_data: dict):
    """Compute duration (timedelta or None) for regenerated occurrences."""
    new_start = update_data.get("start_datetime", template.start_datetime)
    new_end = update_data.get("end_datetime", template.end_datetime)
    if new_end and new_start:
        return new_end - new_start
    if template.end_datetime and template.start_datetime:
        return template.end_datetime - template.start_datetime
    return None


# ── Mutation helpers ───────────────────────────────────────────────────────────

def _geocode_if_changed(update_data: dict, template: Event, db: Session) -> None:
    """If address/city/city_id changed, geocode and inject lat/lng into update_data."""
    if not any(k in update_data for k in ("address", "city", "city_id")):
        return
    new_city = update_data.get("city", template.city)
    new_city_id = update_data.get("city_id", template.city_id)
    if new_city is None and new_city_id is not None:
        city_obj = db.query(City).filter(City.id == new_city_id).first()
        new_city = city_obj.name_en if city_obj else None
    lat, lng = geocode(update_data.get("address", template.address), new_city)
    if lat is not None:
        update_data["latitude"] = lat
        update_data["longitude"] = lng


def _replace_single_event_categories(event_id: int, category_ids: List[int], db: Session) -> None:
    """Replace all EventCategory rows for a single event."""
    db.query(EventCategory).filter(EventCategory.event_id == event_id).delete()
    for pos, cat_id in enumerate(category_ids):
        db.add(EventCategory(event_id=event_id, category_id=cat_id, position=pos))


def _replace_series_categories(series_id: int, category_ids: List[int], db: Session) -> None:
    """Replace EventCategory rows for every event in a series."""
    all_ids = [r.id for r in db.query(Event.id).filter(Event.series_id == series_id).all()]
    if not all_ids:
        return
    db.query(EventCategory).filter(EventCategory.event_id.in_(all_ids)).delete(synchronize_session=False)
    for eid in all_ids:
        for pos, cat_id in enumerate(category_ids):
            db.add(EventCategory(event_id=eid, category_id=cat_id, position=pos))


def _apply_shared_fields_to_series(
    series_id: int, update_data: dict, category_ids: Optional[List[int]], db: Session
) -> None:
    """Bulk-apply shared field changes (and optional category replacement) to all events in a series."""
    if category_ids is not None:
        _validate_category_ids(category_ids, db)
    bulk = {k: v for k, v in update_data.items() if k in _SHARED_EVENT_FIELDS}
    if category_ids is not None:
        bulk["category_id"] = category_ids[0]
    if bulk:
        db.query(Event).filter(Event.series_id == series_id).update(bulk, synchronize_session=False)
    if category_ids is not None:
        _replace_series_categories(series_id, category_ids, db)


def _delete_event_rows(event_ids: List[int], db: Session) -> None:
    """Delete promotions, event_categories, and events.

    EventCategory has ON DELETE CASCADE in PostgreSQL but SQLite does not enforce
    FK constraints without PRAGMA foreign_keys=ON, so we delete child rows explicitly.

    synchronize_session="evaluate" for the Event delete keeps the SQLAlchemy identity
    map in sync, preventing SAWarning when SQLite reuses freed row IDs after bulk deletes.
    """
    if not event_ids:
        return
    db.query(Promotion).filter(Promotion.event_id.in_(event_ids)).delete(synchronize_session=False)
    db.query(EventCategory).filter(EventCategory.event_id.in_(event_ids)).delete(synchronize_session=False)
    db.query(Event).filter(Event.id.in_(event_ids)).delete(synchronize_session="evaluate")


def _create_occurrences(
    db: Session,
    dates: List[datetime],
    shared_fields: dict,
    category_ids: List[int],
    series_id: int,
    duration=None,
    start_index: int = 0,
) -> List[Event]:
    """Insert Event rows and their EventCategory rows for each occurrence datetime."""
    new_events = []
    for i, dt in enumerate(dates, start=start_index):
        end_dt = dt + duration if duration is not None else None
        evt = Event(
            **shared_fields,
            category_id=category_ids[0] if category_ids else None,
            start_datetime=dt,
            end_datetime=end_dt,
            series_id=series_id,
            occurrence_index=i,
            original_start_datetime=dt,
        )
        db.add(evt)
        db.flush()
        new_events.append(evt)
        for pos, cat_id in enumerate(category_ids):
            db.add(EventCategory(event_id=evt.id, category_id=cat_id, position=pos))
    return new_events


# ── Update scope functions ─────────────────────────────────────────────────────

def _update_single(
    event: Event, update_data: dict, category_ids: Optional[List[int]],
    recurrence: Optional[RecurrenceCreate], remove_recurrence: bool, db: Session,
) -> EventResponse:
    if recurrence is not None:
        raise HTTPException(
            status_code=400,
            detail="recurrence cannot be changed for scope=single; use scope=future or scope=series",
        )
    if remove_recurrence and event.series_id is not None:
        event.series_id = None
        event.occurrence_index = None
    if category_ids is not None:
        _validate_category_ids(category_ids, db)
        _replace_single_event_categories(event.id, category_ids, db)
        update_data["category_id"] = category_ids[0]
    if "city_id" in update_data:
        _validate_city_id(update_data["city_id"], db)
    _geocode_if_changed(update_data, event, db)
    for key, value in update_data.items():
        setattr(event, key, value)
    db.commit()
    db.refresh(event)
    return _enrich(event, db)


def _split_future_no_recurrence(
    event: Event, original_series: EventSeries, from_index: int, last_remaining_start,
    update_data: dict, category_ids: Optional[List[int]], db: Session,
) -> EventResponse:
    """Split a series at from_index and apply shared-field updates to the future portion."""
    old_sid = original_series.id

    if original_series.end_type == "count":
        new_series = EventSeries(
            frequency=original_series.frequency,
            interval=original_series.interval,
            end_type="count",
            total_count=original_series.total_count - from_index,
        )
    elif original_series.end_type == "date":
        new_series = EventSeries(
            frequency=original_series.frequency,
            interval=original_series.interval,
            end_type="date",
            end_date=original_series.end_date,
        )
    else:  # never
        new_series = EventSeries(
            frequency=original_series.frequency,
            interval=original_series.interval,
            end_type="never",
        )
    db.add(new_series)
    db.flush()

    db.query(Event).filter(
        Event.series_id == old_sid,
        Event.occurrence_index >= from_index,
    ).update({"series_id": new_series.id}, synchronize_session=False)

    _geocode_if_changed(update_data, event, db)
    _apply_shared_fields_to_series(new_series.id, update_data, category_ids, db)

    adjust_original_series_after_split(original_series, from_index, last_remaining_start)
    if from_index == 0:
        db.delete(original_series)
        db.flush()

    max_start = db.query(func.max(Event.start_datetime)).filter(Event.series_id == new_series.id).scalar()
    new_series.generated_until = max_start

    db.commit()
    refreshed = db.query(Event).filter(Event.id == event.id).first()
    return _enrich(refreshed, db)


def _detach_future_remove_recurrence(
    event: Event, original_series: EventSeries, from_index: int, last_remaining_start,
    update_data: dict, category_ids: Optional[List[int]], db: Session,
) -> EventResponse:
    """Remove recurrence from from_index forward (scope=future + Does not repeat).

    Detaches the selected occurrence as a standalone event and deletes all later
    generated occurrences. Trims the original series to end before from_index.
    """
    old_sid = original_series.id

    # Delete all occurrences strictly after the selected one
    later_ids = [
        r.id for r in db.query(Event.id).filter(
            Event.series_id == old_sid,
            Event.occurrence_index > from_index,
        ).all()
    ]
    _delete_event_rows(later_ids, db)

    # Apply field changes to the selected occurrence before detaching
    if category_ids is not None:
        _validate_category_ids(category_ids, db)
        _replace_single_event_categories(event.id, category_ids, db)
        update_data["category_id"] = category_ids[0]
    _geocode_if_changed(update_data, event, db)
    for key, value in update_data.items():
        setattr(event, key, value)

    # Detach selected occurrence from the series
    event.series_id = None
    event.occurrence_index = None

    # Trim the original series to events before from_index
    adjust_original_series_after_split(original_series, from_index, last_remaining_start)
    if from_index == 0:
        db.delete(original_series)
    else:
        max_start = db.query(func.max(Event.start_datetime)).filter(
            Event.series_id == old_sid
        ).scalar()
        original_series.generated_until = max_start

    db.commit()
    db.refresh(event)
    return _enrich(event, db)


def _split_future_with_new_recurrence(
    event: Event, original_series: EventSeries, from_index: int, last_remaining_start,
    update_data: dict, category_ids: Optional[List[int]],
    recurrence: RecurrenceCreate, db: Session,
) -> EventResponse:
    """Split a series at from_index and regenerate the future portion with a new recurrence rule."""
    template_cats = _get_event_category_ids(event.id, event.category_id, db)
    final_cats = category_ids if category_ids is not None else template_cats
    if final_cats:
        _validate_category_ids(final_cats, db)

    _geocode_if_changed(update_data, event, db)
    new_start = update_data.get("start_datetime", event.start_datetime)
    duration = _compute_duration(event, update_data)
    shared = _build_shared_fields(event, update_data)

    # Capture the original total_count NOW — adjust_original_series_after_split will
    # mutate original_series.total_count to from_index, so we must read it first.
    original_total_count = original_series.total_count
    original_end_type = original_series.end_type

    future_ids = [
        r.id for r in db.query(Event.id).filter(
            Event.series_id == original_series.id,
            Event.occurrence_index >= from_index,
        ).all()
    ]
    _delete_event_rows(future_ids, db)

    adjust_original_series_after_split(original_series, from_index, last_remaining_start)
    if from_index == 0:
        db.delete(original_series)
        db.flush()

    # For count-based splits: if the client echoed back the original total_count
    # unchanged, the new series should contain only the remaining occurrences
    # (original_total_count - from_index). If the user explicitly sent a different
    # count, that value is used as-is.
    effective_count = recurrence.total_count
    if (
        recurrence.end_type == "count"
        and original_end_type == "count"
        and recurrence.total_count == original_total_count
    ):
        effective_count = original_total_count - from_index

    # Use the adjusted count for both date generation and the series row.
    generation_rule = (
        recurrence.model_copy(update={"total_count": effective_count})
        if recurrence.end_type == "count" and effective_count != recurrence.total_count
        else recurrence
    )

    new_series = EventSeries(
        frequency=recurrence.frequency,
        interval=recurrence.interval,
        end_type=recurrence.end_type,
        total_count=effective_count,
        end_date=recurrence.end_date,
    )
    db.add(new_series)
    db.flush()

    dates = generate_dates(generation_rule, new_start)
    new_events = _create_occurrences(db, dates, shared, final_cats, new_series.id, duration)
    new_series.generated_until = dates[-1]

    db.commit()
    db.refresh(new_events[0])
    return _enrich(new_events[0], db)


def _update_future(
    event: Event, update_data: dict, category_ids: Optional[List[int]],
    recurrence: Optional[RecurrenceCreate], remove_recurrence: bool, db: Session,
) -> EventResponse:
    # Standalone event — no recurrence allowed; preserve original behavior (no geocoding)
    if event.series_id is None:
        if recurrence is not None:
            raise HTTPException(
                status_code=400,
                detail="recurrence cannot be set on a standalone event with scope=future",
            )
        if category_ids is not None:
            _validate_category_ids(category_ids, db)
            _replace_single_event_categories(event.id, category_ids, db)
            update_data["category_id"] = category_ids[0]
        for key, value in update_data.items():
            setattr(event, key, value)
        db.commit()
        db.refresh(event)
        return _enrich(event, db)

    original_series = db.query(EventSeries).filter(EventSeries.id == event.series_id).first()
    from_index = event.occurrence_index or 0

    last_remaining_start = (
        db.query(Event.start_datetime).filter(
            Event.series_id == original_series.id,
            Event.occurrence_index == from_index - 1,
        ).scalar()
        if from_index > 0 else None
    )

    # Explicit recurrence removal: detach selected occurrence, delete later ones, trim series
    if remove_recurrence:
        return _detach_future_remove_recurrence(
            event, original_series, from_index, last_remaining_start,
            update_data, category_ids, db,
        )

    remaining_count = db.query(func.count(Event.id)).filter(
        Event.series_id == event.series_id,
        Event.occurrence_index >= from_index,
    ).scalar()

    # Edge case: only one future occurrence → detach as standalone instead of forming a new series
    if remaining_count == 1:
        if recurrence is not None:
            raise HTTPException(
                status_code=400,
                detail="Cannot apply recurrence to a single remaining occurrence; it will become standalone",
            )
        event.series_id = None
        event.occurrence_index = None
        if category_ids is not None:
            _validate_category_ids(category_ids, db)
            _replace_single_event_categories(event.id, category_ids, db)
            update_data["category_id"] = category_ids[0]
        adjust_original_series_after_split(original_series, from_index, last_remaining_start)
        for key, value in update_data.items():
            setattr(event, key, value)
        db.commit()
        db.refresh(event)
        return _enrich(event, db)

    if recurrence is not None:
        return _split_future_with_new_recurrence(
            event, original_series, from_index, last_remaining_start,
            update_data, category_ids, recurrence, db,
        )
    return _split_future_no_recurrence(
        event, original_series, from_index, last_remaining_start,
        update_data, category_ids, db,
    )


def _regenerate_full_series(
    event: Event, original_series: EventSeries, update_data: dict,
    category_ids: Optional[List[int]], recurrence: Optional[RecurrenceCreate], db: Session,
) -> EventResponse:
    """Delete all occurrences and recreate the series from occurrence 0's start."""
    first_event = (
        db.query(Event).filter(
            Event.series_id == original_series.id,
            Event.occurrence_index == 0,
        ).first()
        or event
    )

    _geocode_if_changed(update_data, first_event, db)
    new_start = update_data.get("start_datetime", first_event.start_datetime)
    duration = _compute_duration(first_event, update_data)
    shared = _build_shared_fields(first_event, update_data)

    if category_ids is not None:
        _validate_category_ids(category_ids, db)
        final_cats = category_ids
    else:
        final_cats = _get_event_category_ids(first_event.id, first_event.category_id, db)

    all_ids = [r.id for r in db.query(Event.id).filter(Event.series_id == original_series.id).all()]
    _delete_event_rows(all_ids, db)

    rule = recurrence if recurrence is not None else RecurrenceCreate(
        frequency=original_series.frequency,
        interval=original_series.interval,
        end_type=original_series.end_type,
        total_count=original_series.total_count,
        end_date=original_series.end_date,
    )
    original_series.frequency = rule.frequency
    original_series.interval = rule.interval
    original_series.end_type = rule.end_type
    original_series.total_count = rule.total_count
    original_series.end_date = rule.end_date

    dates = generate_dates(rule, new_start)
    new_events = _create_occurrences(db, dates, shared, final_cats, original_series.id, duration)
    original_series.generated_until = dates[-1]

    db.commit()
    db.refresh(new_events[0])
    return _enrich(new_events[0], db)


def _remove_series_detach_all(
    event: Event, original_series: EventSeries,
    update_data: dict, category_ids: Optional[List[int]], db: Session,
) -> EventResponse:
    """Remove recurrence from entire series (scope=series + Does not repeat).

    All occurrences become standalone events; none are deleted. The EventSeries row
    is removed. Shared field changes are applied to every formerly-series event.
    """
    series_id = original_series.id

    # Snapshot IDs while series_id is still intact
    all_ids = [r.id for r in db.query(Event.id).filter(Event.series_id == series_id).all()]

    # Apply geocoding (uses clicked event as location template)
    _geocode_if_changed(update_data, event, db)

    # Apply category updates to all events before detaching
    if category_ids is not None:
        _validate_category_ids(category_ids, db)
        _replace_series_categories(series_id, category_ids, db)
        update_data["category_id"] = category_ids[0]

    # Apply shared field updates to all events
    bulk = {k: v for k, v in update_data.items() if k in _SHARED_EVENT_FIELDS or k == "category_id"}
    if bulk:
        db.query(Event).filter(Event.id.in_(all_ids)).update(bulk, synchronize_session=False)

    # Detach all events from the series
    db.query(Event).filter(Event.series_id == series_id).update(
        {"series_id": None, "occurrence_index": None},
        synchronize_session=False,
    )

    # Delete the EventSeries row
    db.delete(original_series)

    db.commit()
    db.refresh(event)
    return _enrich(event, db)


def _remove_series_keep_one(
    event: Event, original_series: Optional[EventSeries],
    update_data: dict, category_ids: Optional[List[int]], db: Session,
) -> EventResponse:
    """Keep only the edited occurrence; delete all siblings and the EventSeries row."""
    if original_series is None:
        # Defensive: series already gone — just apply edits and detach
        event.series_id = None
        event.occurrence_index = None
        if category_ids is not None:
            _validate_category_ids(category_ids, db)
            _replace_single_event_categories(event.id, category_ids, db)
            update_data["category_id"] = category_ids[0]
        for key, value in update_data.items():
            setattr(event, key, value)
        db.commit()
        db.refresh(event)
        return _enrich(event, db)

    series_id = original_series.id
    _geocode_if_changed(update_data, event, db)

    if category_ids is not None:
        _validate_category_ids(category_ids, db)
        _replace_single_event_categories(event.id, category_ids, db)
        update_data["category_id"] = category_ids[0]

    # Delete all other occurrences before detaching the target
    db.query(Event).filter(
        Event.series_id == series_id,
        Event.id != event.id,
    ).delete(synchronize_session=False)

    # Detach and apply edits to the target
    event.series_id = None
    event.occurrence_index = None
    for key, value in update_data.items():
        setattr(event, key, value)

    db.delete(original_series)
    db.commit()
    db.refresh(event)
    return _enrich(event, db)


def _convert_standalone_to_series(
    event: Event, update_data: dict, category_ids: Optional[List[int]],
    recurrence: RecurrenceCreate, db: Session,
) -> EventResponse:
    """Convert a standalone event into occurrence 0 of a new recurring series.

    The existing Event row is preserved in-place (id, relations, categories).
    Only the remaining occurrences (indices 1…N-1) are created as new rows.
    """
    _geocode_if_changed(update_data, event, db)

    # Apply any edited fields to the existing event row
    for key, value in update_data.items():
        setattr(event, key, value)

    # Update or preserve categories
    if category_ids is not None:
        _validate_category_ids(category_ids, db)
        _replace_single_event_categories(event.id, category_ids, db)
        event.category_id = category_ids[0]
        final_cats = category_ids
    else:
        final_cats = _get_event_category_ids(event.id, event.category_id, db)

    # Create the series row
    series = EventSeries(
        frequency=recurrence.frequency,
        interval=recurrence.interval,
        end_type=recurrence.end_type,
        total_count=recurrence.total_count,
        end_date=recurrence.end_date,
    )
    db.add(series)
    db.flush()

    # Attach the existing event as occurrence 0
    event.series_id = series.id
    event.occurrence_index = 0
    event.original_start_datetime = event.start_datetime
    db.flush()

    # Generate all dates from the event's (possibly updated) start datetime
    start = event.start_datetime
    duration = _compute_duration(event, {})
    dates = generate_dates(recurrence, start)

    # Build shared fields from the now-updated event
    shared = _build_shared_fields(event, {})

    # Create occurrences 1…N-1 (occurrence 0 is the preserved event)
    if len(dates) > 1:
        _create_occurrences(
            db, dates[1:], shared, final_cats, series.id, duration, start_index=1
        )

    series.generated_until = dates[-1]
    db.commit()
    db.refresh(event)
    return _enrich(event, db)


def _update_series(
    event: Event, update_data: dict, category_ids: Optional[List[int]],
    recurrence: Optional[RecurrenceCreate], remove_recurrence: bool, db: Session,
) -> EventResponse:
    # Standalone event — no recurrence allowed; preserve original behavior (no geocoding)
    if event.series_id is None:
        if recurrence is not None:
            raise HTTPException(
                status_code=400,
                detail="Cannot set recurrence on a standalone event via scope=series",
            )
        if category_ids is not None:
            _validate_category_ids(category_ids, db)
            _replace_single_event_categories(event.id, category_ids, db)
            update_data["category_id"] = category_ids[0]
        for key, value in update_data.items():
            setattr(event, key, value)
        db.commit()
        db.refresh(event)
        return _enrich(event, db)

    original_series = db.query(EventSeries).filter(EventSeries.id == event.series_id).first()

    # Explicit recurrence removal: detach all occurrences as standalone, delete the series row
    if remove_recurrence:
        return _remove_series_detach_all(event, original_series, update_data, category_ids, db)

    if recurrence is not None or "start_datetime" in update_data:
        return _regenerate_full_series(event, original_series, update_data, category_ids, recurrence, db)

    # Bulk shared-field update (no datetime change, no regeneration)
    _geocode_if_changed(update_data, event, db)
    _apply_shared_fields_to_series(event.series_id, update_data, category_ids, db)
    db.commit()
    refreshed = db.query(Event).filter(Event.id == event.id).first()
    return _enrich(refreshed, db)


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[EventResponse])
def get_events(
    organization_id: Optional[int] = None,
    series_id: Optional[int] = None,
    category_id: Optional[int] = None,
    city_id: Optional[int] = None,
    user_latitude: Optional[float] = None,
    user_longitude: Optional[float] = None,
    radius_km: float = 25,
    include_past: bool = False,
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
        if series_id is not None:
            query = query.filter(Event.series_id == series_id)
        if cat_filter is not None:
            query = query.filter(cat_filter)
        if city_id is not None:
            query = query.filter(or_(
                Event.city_id == city_id,
                Event.is_nationwide.is_(True),
            ))
        if not include_past:
            query = query.filter(Event.start_datetime >= now)

        rows = query.all()
        cities = _city_map([ev.city_id for ev, _, _ in rows], db)
        smap = _series_map([ev.series_id for ev, _, _ in rows], db)
        out = []
        for event, dist_km, _ in rows:
            resp = _enrich(event, db, city_map=cities, series_map=smap)
            resp = resp.model_copy(update={
                "distance_km": round(float(dist_km), 2) if dist_km is not None else None
            })
            out.append(resp)
        return out

    now = datetime.utcnow()
    query = db.query(Event)
    if organization_id is not None:
        query = query.filter(Event.organization_id == organization_id)
    if series_id is not None:
        query = query.filter(Event.series_id == series_id)
    if cat_filter is not None:
        query = query.filter(cat_filter)
    if city_id is not None:
        query = query.filter(or_(
            Event.city_id == city_id,
            Event.is_nationwide.is_(True),
        ))
    if not include_past:
        query = query.filter(Event.start_datetime >= now)
    events = query.order_by(Event.start_datetime.asc()).all()
    cities = _city_map([ev.city_id for ev in events], db)
    smap = _series_map([ev.series_id for ev in events], db)
    return [_enrich(e, db, city_map=cities, series_map=smap) for e in events]


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

    recurrence: Optional[RecurrenceCreate] = event.recurrence
    event_data = event.model_dump()
    category_ids = event_data.pop("category_ids")
    event_data.pop("recurrence", None)

    _validate_category_ids(category_ids, db)
    city_name_en = _validate_city_id(event_data.get("city_id"), db)

    event_data["category_id"] = category_ids[0]

    geocode_city = event_data.get("city") or city_name_en
    lat, lng = geocode(event_data.get("address"), geocode_city)
    if lat is not None:
        event_data["latitude"] = lat
        event_data["longitude"] = lng

    if recurrence is None:
        new_event = Event(**event_data)
        db.add(new_event)
        db.flush()
        for pos, cat_id in enumerate(category_ids):
            db.add(EventCategory(event_id=new_event.id, category_id=cat_id, position=pos))
        db.commit()
        db.refresh(new_event)
        return _enrich(new_event, db)

    # Recurring series
    series = EventSeries(
        frequency=recurrence.frequency,
        interval=recurrence.interval,
        end_type=recurrence.end_type,
        total_count=recurrence.total_count,
        end_date=recurrence.end_date,
    )
    db.add(series)
    db.flush()

    first_start = event_data.pop("start_datetime")
    end_datetime = event_data.pop("end_datetime", None)
    duration = (end_datetime - first_start) if end_datetime and first_start else None

    shared = {k: v for k, v in event_data.items()
               if k not in ("category_id", "series_id", "occurrence_index", "original_start_datetime")}

    dates = generate_dates(recurrence, first_start)
    new_events = _create_occurrences(db, dates, shared, category_ids, series.id, duration)

    series.generated_until = dates[-1]
    db.commit()
    db.refresh(new_events[0])
    return _enrich(new_events[0], db)


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
    scope: str = "single",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if scope not in ("single", "future", "series"):
        raise HTTPException(status_code=400, detail="scope must be single, future, or series")

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == event.organization_id,
        OrganizationUser.user_id == current_user.id,
    ).first()
    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")

    recurrence: Optional[RecurrenceCreate] = event_update.recurrence
    remove_recurrence: bool = (
        "recurrence" in event_update.model_fields_set and event_update.recurrence is None
    )
    update_data = event_update.model_dump(exclude_unset=True)
    category_ids: Optional[List[int]] = update_data.pop("category_ids", None)
    update_data.pop("recurrence", None)

    # Removing recurrence: keep only this occurrence, delete all siblings, delete series.
    # Scope is irrelevant for this operation.
    if remove_recurrence and event.series_id is not None:
        original_series = db.query(EventSeries).filter(EventSeries.id == event.series_id).first()
        return _remove_series_keep_one(event, original_series, update_data, category_ids, db)

    # Adding recurrence to a standalone event: convert it to a series in-place.
    # Scope is irrelevant — the existing event always becomes occurrence 0.
    if recurrence is not None and event.series_id is None:
        return _convert_standalone_to_series(event, update_data, category_ids, recurrence, db)

    if scope == "single":
        return _update_single(event, update_data, category_ids, recurrence, remove_recurrence, db)
    if scope == "future":
        return _update_future(event, update_data, category_ids, recurrence, remove_recurrence, db)
    return _update_series(event, update_data, category_ids, recurrence, remove_recurrence, db)


@router.delete("/{event_id}")
def delete_event(
    event_id: int,
    scope: str = "single",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if scope not in ("single", "future", "series"):
        raise HTTPException(status_code=400, detail="scope must be single, future, or series")

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == event.organization_id,
        OrganizationUser.user_id == current_user.id,
    ).first()
    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")

    if scope == "single":
        db.query(Promotion).filter(Promotion.event_id == event_id).delete()
        db.delete(event)
        db.commit()
        return {"message": "Event deleted"}

    if scope == "future":
        if event.series_id is None:
            db.query(Promotion).filter(Promotion.event_id == event_id).delete()
            db.delete(event)
            db.commit()
            return {"message": "Event deleted"}

        series_id = event.series_id
        from_index = event.occurrence_index

        future_ids = [
            r.id for r in db.query(Event.id).filter(
                Event.series_id == series_id,
                Event.occurrence_index >= from_index,
            ).all()
        ]
        _delete_event_rows(future_ids, db)

        remaining = db.query(func.count(Event.id)).filter(Event.series_id == series_id).scalar()
        if remaining == 0:
            db.query(EventSeries).filter(EventSeries.id == series_id).delete()
        else:
            series = db.query(EventSeries).filter(EventSeries.id == series_id).first()
            if series:
                max_start = db.query(func.max(Event.start_datetime)).filter(
                    Event.series_id == series_id
                ).scalar()
                series.generated_until = max_start
        db.commit()
        return {"message": "Future occurrences deleted"}

    # scope == "series"
    if event.series_id is None:
        db.query(Promotion).filter(Promotion.event_id == event_id).delete()
        db.delete(event)
        db.commit()
        return {"message": "Event deleted"}

    series_id = event.series_id
    all_ids = [r.id for r in db.query(Event.id).filter(Event.series_id == series_id).all()]
    _delete_event_rows(all_ids, db)
    db.query(EventSeries).filter(EventSeries.id == series_id).delete()
    db.commit()
    return {"message": "Series deleted"}
