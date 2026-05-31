from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.classes import Class
from app.models.favorite import Favorite
from app.models.group import Group
from app.models.group_schedule import GroupSchedule
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.promotion import Promotion
from app.models.review import Review
from app.models.user import User
from app.schemas.class_search import ClassSearchParams
from app.schemas.classes import ClassCreate, ClassResponse, ClassUpdate

router = APIRouter(
    prefix="/classes",
    tags=["classes"]
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


def _build_class_response(class_obj, org_name, cat_name, distance_km=None):
    return ClassResponse(
        id=class_obj.id,
        organization_id=class_obj.organization_id,
        category_id=class_obj.category_id,
        name=class_obj.name,
        description=class_obj.description,
        image_url=class_obj.image_url,
        price=class_obj.price,
        price_type=class_obj.price_type,
        status=class_obj.status,
        created_at=class_obj.created_at,
        organization_name=org_name,
        category_name=cat_name,
        distance_km=distance_km,
    )


@router.get("/", response_model=List[ClassResponse])
def get_classes(
    organization_id: Optional[int] = None,
    user_latitude: Optional[float] = None,
    user_longitude: Optional[float] = None,
    radius_km: float = 25,
    db: Session = Depends(get_db),
):
    from app.models.category import Category as CategoryModel

    if user_latitude is not None and user_longitude is not None:
        now = datetime.utcnow()
        dist = _haversine(user_latitude, user_longitude,
                          Organization.latitude, Organization.longitude)
        best_rank = func.coalesce(func.max(_promo_rank(Promotion.promotion_type)), 0)

        query = (
            db.query(
                Class,
                Organization.name.label("org_name"),
                CategoryModel.name.label("cat_name"),
                dist.label("dist_km"),
                best_rank.label("rank"),
            )
            .join(Organization, Class.organization_id == Organization.id)
            .outerjoin(CategoryModel, Class.category_id == CategoryModel.id)
            .outerjoin(
                Promotion,
                (Promotion.organization_id == Organization.id) &
                (Promotion.start_date <= now) &
                (Promotion.end_date >= now),
            )
            .filter(
                Organization.latitude.isnot(None),
                Organization.longitude.isnot(None),
                dist <= radius_km,
            )
            .group_by(Class.id, Organization.id, CategoryModel.id)
            .order_by(best_rank.desc(), dist.asc())
        )
        if organization_id is not None:
            query = query.filter(Class.organization_id == organization_id)

        return [
            _build_class_response(c, org_name, cat_name, round(float(d), 2))
            for c, org_name, cat_name, d, _ in query.all()
        ]

    # No radius filter — existing behaviour
    query = (
        db.query(Class, Organization.name.label("org_name"), CategoryModel.name.label("cat_name"))
        .join(Organization, Class.organization_id == Organization.id)
        .outerjoin(CategoryModel, Class.category_id == CategoryModel.id)
    )
    if organization_id is not None:
        query = query.filter(Class.organization_id == organization_id)
    return [_build_class_response(c, org_name, cat_name) for c, org_name, cat_name in query.all()]


@router.post("/", response_model=ClassResponse)
def create_class(
    class_data: ClassCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == class_data.organization_id,
        OrganizationUser.user_id == current_user.id
    ).first()

    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")

    new_class = Class(**class_data.model_dump())

    db.add(new_class)
    db.commit()
    db.refresh(new_class)

    return new_class

@router.get("/search")
def search_classes(
    category_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    city: Optional[str] = None,
    age: Optional[int] = None,
    day_of_week: Optional[int] = None,

    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    price_type: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    distance_km: Optional[int] = None,

    limit: int = 20,
    offset: int = 0,
    sort_by: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(
        Class,
        func.avg(Review.rating).label("rating"),
        func.count(Favorite.id).label("is_favorite")
    )

    query = query.join(Organization, Class.organization_id == Organization.id)
    query = query.outerjoin(Group, Group.class_id == Class.id)
    query = query.outerjoin(GroupSchedule, GroupSchedule.group_id == Group.id)
    query = query.outerjoin(Review, Review.organization_id == Organization.id)
    query = query.outerjoin(
        Favorite,
        (Favorite.entity_id == Organization.id) &
        (Favorite.entity_type == "organization") &
        (Favorite.user_id == current_user.id)
    )
    query = query.group_by(Class.id, Favorite.id)

    if category_id is not None:
        query = query.filter(Class.category_id == category_id)
    if city:
        query = query.filter(Organization.city == city)

    if search:
        term = f"%{search}%"

        query = query.filter(
            or_(
                Class.name.ilike(term),
                Class.description.ilike(term),
                Organization.name.ilike(term)
            )
        )

    distance = None
    if lat is not None and lng is not None:
        if distance_km is None:
            distance_km = 10

        lat_delta = distance_km / 111
        lng_delta = distance_km / (111 * func.cos(func.radians(lat)))

        query = query.filter(
            Organization.latitude.between(lat - lat_delta, lat + lat_delta),
            Organization.longitude.between(lng - lng_delta, lng + lng_delta)
        )

        distance = 6371 * func.acos(
            func.cos(func.radians(lat)) *
            func.cos(func.radians(Organization.latitude)) *
            func.cos(func.radians(Organization.longitude) - func.radians(lng)) +
            func.sin(func.radians(lat)) *
            func.sin(func.radians(Organization.latitude))
        )

        query = query.filter(distance <= distance_km)

    if age is not None:
        query = query.filter(
            Group.age_from <= age,
            Group.age_to >= age
        )
    if day_of_week is not None:
        query = query.filter(GroupSchedule.day_of_week == day_of_week)

    if min_price is not None or max_price is not None:

        conditions = []

        if min_price is not None:
            conditions.append(Class.price >= min_price)

        if max_price is not None:
            conditions.append(Class.price <= max_price)

        query = query.filter(
            or_(
                Class.price.is_(None),
                *conditions
            )
        )

    total = query.with_entities(Class.id).distinct().count()
    if sort_by == "price":
        query = query.order_by(Class.price)

    elif sort_by == "newest":
        query = query.order_by(Class.created_at.desc())

    elif sort_by == "distance" and distance is not None:
        query = query.order_by(distance)

    elif sort_by == "rating":
        query = query.order_by(func.avg(Review.rating).desc())

    results = query.limit(limit).offset(offset).all()

    classes = []

    for row in results:
        class_obj = row[0]
        rating = row[1]
        is_favorite = row[2] > 0

        classes.append({
            "class": class_obj,
            "rating": rating,
            "is_favorite": is_favorite
        })

    return {
        "items": classes,
        "total": total,
        "limit": limit,
        "offset": offset
    }

@router.get("/{class_id}", response_model=ClassResponse)
def get_class(
    class_id: int,
    db: Session = Depends(get_db)
):
    class_obj = db.query(Class).filter(Class.id == class_id).first()

    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")

    return class_obj

@router.put("/{class_id}", response_model=ClassResponse)
def update_class(
    class_id: int,
    class_update: ClassUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    class_obj = db.query(Class).filter(Class.id == class_id).first()

    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")

    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == class_obj.organization_id,
        OrganizationUser.user_id == current_user.id
    ).first()

    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")

    for key, value in class_update.model_dump(exclude_unset=True).items():
        setattr(class_obj, key, value)

    db.commit()
    db.refresh(class_obj)

    return class_obj

@router.get("/{class_id}/details")
def get_class_details(
    class_id: int,
    db: Session = Depends(get_db)
):

    class_obj = db.query(Class).filter(Class.id == class_id).first()

    organization = db.query(Organization).filter(
        Organization.id == class_obj.organization_id
    ).first()

    groups = db.query(Group).filter(
        Group.class_id == class_id
    ).all()

    group_ids = [g.id for g in groups]

    schedules = db.query(GroupSchedule).filter(
        GroupSchedule.group_id.in_(group_ids)
    ).all()

    reviews = db.query(Review).filter(
        Review.organization_id == organization.id
    ).order_by(Review.created_at.desc()).limit(10).all()

    rating = None
    if reviews:
        rating = sum(r.rating for r in reviews) / len(reviews)

    if not class_obj:
        return {"error": "class not found"}

    return {
        "class": class_obj,
        "organization": organization,
        "groups": groups,
        "schedules": schedules,
        "rating": rating,
        "reviews": reviews
    }


@router.delete("/{class_id}")
def delete_class(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    class_obj = db.query(Class).filter(Class.id == class_id).first()
    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")

    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == class_obj.organization_id,
        OrganizationUser.user_id == current_user.id
    ).first()

    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")


    db.delete(class_obj)
    db.commit()

    return {"message": "Class deleted"}

