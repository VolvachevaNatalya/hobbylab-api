from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.dependencies import get_db
from app.models.favorite import Favorite
from app.schemas.favorite import FavoriteCreate, FavoriteResponse
from app.core.auth import get_current_user
from app.models.user import User


router = APIRouter(
    prefix="/favorites",
    tags=["favorites"]
)


@router.get("/", response_model=List[FavoriteResponse])
def get_favorites(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(Favorite).filter(Favorite.user_id == current_user.id).all()


@router.post("/", response_model=FavoriteResponse)
def add_favorite(
    favorite: FavoriteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_favorite = Favorite(
        user_id=current_user.id,
        entity_type=favorite.entity_type,
        entity_id=favorite.entity_id
    )

    db.add(new_favorite)
    db.commit()
    db.refresh(new_favorite)

    return new_favorite


@router.delete("/{favorite_id}")
def delete_favorite(
    favorite_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    favorite = db.query(Favorite).filter(
        Favorite.id == favorite_id,
        Favorite.user_id == current_user.id
    ).first()

    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")

    db.delete(favorite)
    db.commit()

    return {"message": "Favorite deleted"}