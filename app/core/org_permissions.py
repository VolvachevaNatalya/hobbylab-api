from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.organization_user import OrganizationUser


def require_owner(org_id: int, user_id: int, db: Session) -> OrganizationUser:
    membership = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org_id,
        OrganizationUser.user_id == user_id,
        OrganizationUser.role == "owner",
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Only the organization owner can perform this action")
    return membership


def require_owner_or_admin(org_id: int, user_id: int, db: Session) -> OrganizationUser:
    membership = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org_id,
        OrganizationUser.user_id == user_id,
        OrganizationUser.role.in_(["owner", "admin"]),
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Owner or admin access required")
    return membership


def get_membership(org_id: int, user_id: int, db: Session) -> Optional[OrganizationUser]:
    return db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org_id,
        OrganizationUser.user_id == user_id,
    ).first()
