from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.dependencies import get_db
from app.models.review_image import ReviewImage
from app.schemas.review_image import ReviewImageCreate, ReviewImageResponse


router = APIRouter(
    prefix="/review-images",
    tags=["review_images"]
)


@router.post("/", response_model=ReviewImageResponse)
def create_review_image(
    image: ReviewImageCreate,
    db: Session = Depends(get_db)
):
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
    return db.query(ReviewImage).filter(
        ReviewImage.review_id == review_id
    ).all()


@router.delete("/{image_id}")
def delete_review_image(
    image_id: int,
    db: Session = Depends(get_db)
):
    image = db.query(ReviewImage).filter(
        ReviewImage.id == image_id
    ).first()

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    db.delete(image)
    db.commit()

    return {"message": "Image deleted"}