from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.city import City
from app.schemas.city import CityResponse

router = APIRouter(prefix="/cities", tags=["cities"])


@router.get("/", response_model=List[CityResponse])
def get_cities(
    q: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(City).filter(City.is_active == True)
    if q:
        pat = f"%{q}%"
        query = query.filter(
            or_(
                City.name_en.ilike(pat),
                City.name_he.contains(q),
                City.name_ru.ilike(pat),
            )
        )
    return query.order_by(City.name_en).limit(limit).all()
