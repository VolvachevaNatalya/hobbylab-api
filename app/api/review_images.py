from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.review import Review
from app.models.review_image import ReviewImage
from app.models.user import User
from app.schemas.review_image import ReviewImageCreate, ReviewImageResponse

router = APIRouter(
    prefix="/review-images",
    tags=["review_images"]
)


def _require_review_owner(review: Review, current_user: User) -> None:
    if current_user.is_system_admin:
        return
    if review.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")


@router.post("/", response_model=ReviewImageResponse)
def create_review_image(
    image: ReviewImageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = db.query(Review).filter(Review.id == image.review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    _require_review_owner(review, current_user)

    new_image = ReviewImage(**image.model_dump())
    db.add(new_image)
    db.commit()
    db.refresh(new_image)
    return new_image


@router.get("/review/{review_id}", response_model=List[ReviewImageResponse])
def get_images_by_review(
    review_id: int,
    db: Session = Depends(get_db)
):
    return db.query(ReviewImage).filter(ReviewImage.review_id == review_id).all()


@router.delete("/{image_id}")
def delete_review_image(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    image = db.query(ReviewImage).filter(ReviewImage.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    review = db.query(Review).filter(Review.id == image.review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    _require_review_owner(review, current_user)

    db.delete(image)
    db.commit()
    return {"message": "Image deleted"}
