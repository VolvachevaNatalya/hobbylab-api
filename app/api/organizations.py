from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db.dependencies import get_db
from app.schemas.organization import OrganizationCreate, OrganizationResponse
from app.models.organization import Organization
from app.models.notification import Notification
from app.core.auth import get_current_user
from app.models.user import User
from app.models.organization_user import OrganizationUser
from app.schemas.organization import OrganizationUpdate

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/", response_model=List[OrganizationResponse])
def get_organizations(db: Session = Depends(get_db)):
    return (
        db.query(Organization)
        .filter(Organization.status == "active", Organization.verified == True)
        .all()
    )


@router.post("/", response_model=OrganizationResponse)
def create_organization(
    org: OrganizationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    organization = Organization(**org.model_dump(), status="pending", verified=False)
    db.add(organization)
    db.flush()

    org_user = OrganizationUser(
        organization_id=organization.id,
        user_id=current_user.id,
        role="owner"
    )
    db.add(org_user)

    admin_notification = Notification(
        user_id=1,
        organization_id=organization.id,
        title="New organization pending approval",
        message=f"New organization pending approval: {organization.name}",
        type="new_organization",
    )
    db.add(admin_notification)

    db.commit()
    db.refresh(organization)

    return organization


@router.get("/my", response_model=List[OrganizationResponse])
def get_my_organizations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    orgs = (
        db.query(Organization)
        .join(OrganizationUser, Organization.id == OrganizationUser.organization_id)
        .filter(OrganizationUser.user_id == current_user.id)
        .all()
    )

    return orgs

@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    organization_id: int,
    db: Session = Depends(get_db)
):
    organization = (
        db.query(Organization)
        .filter(Organization.id == organization_id)
        .first()
    )

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    return organization

@router.put("/{organization_id}", response_model=OrganizationResponse)
def update_organization(
    organization_id: int,
    org_update: OrganizationUpdate,
    db: Session = Depends(get_db)
):
    organization = db.query(Organization).filter(Organization.id == organization_id).first()

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    for key, value in org_update.model_dump(exclude_unset=True).items():
        setattr(organization, key, value)

    db.commit()
    db.refresh(organization)

    return organization

@router.delete("/{organization_id}")
def delete_organization(
    organization_id: int,
    db: Session = Depends(get_db)
):
    organization = db.query(Organization).filter(Organization.id == organization_id).first()

    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    db.delete(organization)
    db.commit()

    return {"message": "Organization deleted"}