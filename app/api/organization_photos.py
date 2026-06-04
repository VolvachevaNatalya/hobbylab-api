from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.dependencies import get_db
from app.models.organization import Organization
from app.models.organization_photo import OrganizationPhoto
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.schemas.organization_photo import OrganizationPhotoCreate, OrganizationPhotoResponse

router = APIRouter(tags=["organization_photos"])

MAX_PHOTOS = 10


def _require_org_owner(org_id: int, current_user: User, db: Session) -> Organization:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    membership = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org_id,
        OrganizationUser.user_id == current_user.id,
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not authorized")
    return org


@router.get(
    "/organizations/{org_id}/photos",
    response_model=List[OrganizationPhotoResponse],
)
def get_photos(org_id: int, db: Session = Depends(get_db)):
    if not db.query(Organization).filter(Organization.id == org_id).first():
        raise HTTPException(status_code=404, detail="Organization not found")
    return (
        db.query(OrganizationPhoto)
        .filter(OrganizationPhoto.organization_id == org_id)
        .order_by(OrganizationPhoto.created_at)
        .limit(MAX_PHOTOS)
        .all()
    )


@router.post(
    "/organizations/{org_id}/photos",
    response_model=OrganizationPhotoResponse,
    status_code=201,
)
def add_photo(
    org_id: int,
    payload: OrganizationPhotoCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_org_owner(org_id, current_user, db)

    count = (
        db.query(OrganizationPhoto)
        .filter(OrganizationPhoto.organization_id == org_id)
        .count()
    )
    if count >= MAX_PHOTOS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_PHOTOS} photos per organization",
        )

    photo = OrganizationPhoto(
        organization_id=org_id,
        photo_url=payload.photo_url,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


@router.delete("/organizations/{org_id}/photos/{photo_id}", status_code=204)
def delete_photo(
    org_id: int,
    photo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_org_owner(org_id, current_user, db)

    photo = db.query(OrganizationPhoto).filter(
        OrganizationPhoto.id == photo_id,
        OrganizationPhoto.organization_id == org_id,
    ).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    db.delete(photo)
    db.commit()
