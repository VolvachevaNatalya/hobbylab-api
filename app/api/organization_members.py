from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.org_permissions import require_owner, require_owner_or_admin
from app.db.dependencies import get_db
from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.user import User
from app.schemas.organization_member import MemberResponse, MemberRoleUpdate

router = APIRouter(prefix="/organizations", tags=["organization-members"])


def _get_org_or_404(org_id: int, db: Session) -> Organization:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def _get_member_or_404(org_id: int, user_id: int, db: Session) -> OrganizationUser:
    membership = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == org_id,
        OrganizationUser.user_id == user_id,
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")
    return membership


@router.get("/{org_id}/members", response_model=List[MemberResponse])
def list_members(
    org_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_org_or_404(org_id, db)
    require_owner_or_admin(org_id, current_user.id, db)

    rows = (
        db.query(OrganizationUser, User)
        .join(User, User.id == OrganizationUser.user_id)
        .filter(OrganizationUser.organization_id == org_id)
        .order_by(OrganizationUser.created_at.asc())
        .all()
    )

    return [
        MemberResponse(
            user_id=membership.user_id,
            name=user.name,
            email=user.email,
            role=membership.role,
            joined_at=membership.created_at,
        )
        for membership, user in rows
    ]


@router.patch("/{org_id}/members/{user_id}/role", response_model=MemberResponse)
def update_member_role(
    org_id: int,
    user_id: int,
    payload: MemberRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_org_or_404(org_id, db)
    require_owner(org_id, current_user.id, db)

    target = _get_member_or_404(org_id, user_id, db)
    if target.role == "owner":
        raise HTTPException(status_code=403, detail="Cannot change the owner's role")

    target.role = payload.role
    db.commit()
    db.refresh(target)

    user = db.query(User).filter(User.id == user_id).first()
    return MemberResponse(
        user_id=target.user_id,
        name=user.name,
        email=user.email,
        role=target.role,
        joined_at=target.created_at,
    )


@router.delete("/{org_id}/members/{user_id}")
def remove_member(
    org_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_org_or_404(org_id, db)
    require_owner_or_admin(org_id, current_user.id, db)

    target = _get_member_or_404(org_id, user_id, db)

    if target.user_id == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot remove yourself from the organization")
    if target.role == "owner":
        raise HTTPException(status_code=403, detail="Cannot remove an owner")

    db.delete(target)
    db.commit()
    return {"message": "Member removed"}
