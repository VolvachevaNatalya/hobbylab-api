from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.dependencies import get_db
from app.models.review import Review
from app.models.review_image import ReviewImage
from app.schemas.review import ReviewCreate, ReviewResponse, ReviewUpdate
from app.models.user import User
from app.core.auth import get_current_user


def _attach_user_name(review: Review, db: Session) -> dict:
    data = {c.name: getattr(review, c.name) for c in review.__table__.columns}
    user = db.query(User).filter(User.id == review.user_id).first()
    data['user_name'] = user.name if user else None
    images = db.query(ReviewImage).filter(ReviewImage.review_id == review.id).all()
    data['photo_urls'] = [img.image_url for img in images]
    return data


router = APIRouter(
    prefix="/reviews",
    tags=["reviews"]
)


@router.post("/", response_model=ReviewResponse)
def create_review(
    review: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    existing = db.query(Review).filter(
        Review.user_id == current_user.id,
        Review.organization_id == review.organization_id
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Review already exists")

    new_review = Review(
        user_id=current_user.id,
        organization_id=review.organization_id,
        rating=review.rating,
        comment=review.comment
    )

    db.add(new_review)
    db.flush()  # populate new_review.id before inserting images

    if review.photo_urls:
        for url in review.photo_urls[:5]:
            db.add(ReviewImage(review_id=new_review.id, image_url=url))

    db.commit()
    db.refresh(new_review)

    return _attach_user_name(new_review, db)


@router.get("/organization/{organization_id}", response_model=List[ReviewResponse])
def get_reviews_by_org(
    organization_id: int,
    db: Session = Depends(get_db)
):
    reviews = db.query(Review).filter(
        Review.organization_id == organization_id
    ).all()
    return [_attach_user_name(r, db) for r in reviews]


@router.put("/{review_id}", response_model=ReviewResponse)
def update_review(
    review_id: int,
    review_update: ReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    review = db.query(Review).filter(Review.id == review_id).first()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    if review.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")

    for key, value in review_update.model_dump(exclude_unset=True).items():
        setattr(review, key, value)

    db.commit()
    db.refresh(review)

    return _attach_user_name(review, db)


@router.delete("/{review_id}")
def delete_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    review = db.query(Review).filter(Review.id == review_id).first()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    if review.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission")

    db.delete(review)
    db.commit()

    return {"message": "Review deleted"}