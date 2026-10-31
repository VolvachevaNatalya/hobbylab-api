from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_system_admin
from app.db.dependencies import get_db
from app.models.promotion import Promotion
from app.models.user import User
from app.schemas.promotion import PromotionCreate, PromotionUpdate

router = APIRouter(prefix="/promotions", tags=["promotions"])


@router.get("/")
def get_promotions(db: Session = Depends(get_db)):
    return db.query(Promotion).all()


@router.get("/{promotion_id}")
def get_promotion(
    promotion_id: int,
    db: Session = Depends(get_db),
):
    return (
        db.query(Promotion)
        .filter(Promotion.id == promotion_id)
        .first()
    )


@router.post("/")
def create_promotion(
    data: PromotionCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_system_admin),
):
    promotion = Promotion(**data.dict())
    db.add(promotion)
    db.commit()
    db.refresh(promotion)
    return promotion


@router.put("/{promotion_id}")
def update_promotion(
    promotion_id: int,
    data: PromotionUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_system_admin),
):
    promotion = (
        db.query(Promotion)
        .filter(Promotion.id == promotion_id)
        .first()
    )
    if not promotion:
        raise HTTPException(status_code=404, detail="Not found")

    for key, value in data.dict().items():
        setattr(promotion, key, value)

    db.commit()
    db.refresh(promotion)
    return promotion


@router.delete("/{promotion_id}")
def delete_promotion(
    promotion_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_system_admin),
):
    promotion = (
        db.query(Promotion)
        .filter(Promotion.id == promotion_id)
        .first()
    )
    if not promotion:
        raise HTTPException(status_code=404, detail="Not found")

    db.delete(promotion)
    db.commit()
    return {"status": "deleted"}
