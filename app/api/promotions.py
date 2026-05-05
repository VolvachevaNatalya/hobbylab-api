from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.core.auth import get_current_user
from app.models.promotion import Promotion
from app.models.user import User
from app.schemas.promotion import PromotionCreate, PromotionUpdate

router = APIRouter(prefix="/promotions", tags=["promotions"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def get_promotions(
    db: Session = Depends(get_db)
):
    return db.query(Promotion).all()


@router.post("/")
def create_promotion(
    data: PromotionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    promotion = Promotion(**data.dict())

    db.add(promotion)
    db.commit()
    db.refresh(promotion)

    return promotion

@router.get("/{promotion_id}")
def get_promotion(
    promotion_id: int,
    db: Session = Depends(get_db)
):
    return (
        db.query(Promotion)
        .filter(Promotion.id == promotion_id)
        .first()
    )

@router.delete("/{promotion_id}")
def delete_promotion(
    promotion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    promotion = (
        db.query(Promotion)
        .filter(Promotion.id == promotion_id)
        .first()
    )

    if not promotion:
        return {"error": "not found"}

    db.delete(promotion)
    db.commit()

    return {"status": "deleted"}

@router.put("/{promotion_id}")
def update_promotion(
    promotion_id: int,
    data: PromotionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    promotion = (
        db.query(Promotion)
        .filter(Promotion.id == promotion_id)
        .first()
    )

    if not promotion:
        return {"error": "not found"}

    for key, value in data.dict().items():
        setattr(promotion, key, value)

    db.commit()
    db.refresh(promotion)

    return promotion