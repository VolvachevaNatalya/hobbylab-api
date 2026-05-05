from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.dependencies import get_db
from app.models.group import Group
from app.schemas.group import GroupCreate, GroupResponse, GroupUpdate
from app.models.organization_user import OrganizationUser
from app.core.auth import get_current_user
from app.models.user import User
from app.models.classes import Class

router = APIRouter(
    prefix="/groups",
    tags=["groups"]
)


@router.get("/", response_model=List[GroupResponse])
def get_groups(db: Session = Depends(get_db)):
    return db.query(Group).all()


@router.post("/", response_model=GroupResponse)
def create_group(
    group: GroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    class_obj = db.query(Class).filter(Class.id == group.class_id).first()

    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")

    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == class_obj.organization_id,
        OrganizationUser.user_id == current_user.id
    ).first()

    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")


    new_group = Group(**group.model_dump())

    db.add(new_group)
    db.commit()
    db.refresh(new_group)

    return new_group

@router.get("/class/{class_id}", response_model=List[GroupResponse])
def get_groups_by_class(
    class_id: int,
    db: Session = Depends(get_db)
):
    groups = db.query(Group).filter(Group.class_id == class_id).all()
    return groups

@router.put("/{group_id}", response_model=GroupResponse)
def update_group(
    group_id: int,
    group_update: GroupUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    group_obj = db.query(Group).filter(Group.id == group_id).first()
    if not group_obj:
        raise HTTPException(status_code=404, detail="Group not found")

    class_obj = db.query(Class).filter(Class.id == group_obj.class_id).first()
    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")

    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == class_obj.organization_id,
        OrganizationUser.user_id == current_user.id
    ).first()

    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")

    for key, value in group_update.model_dump(exclude_unset=True).items():
        setattr(group_obj, key, value)

    db.commit()
    db.refresh(group_obj)

    return group_obj

@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    group = db.query(Group).filter(Group.id == group_id).first()

    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    class_obj = db.query(Class).filter(Class.id == group.class_id).first()
    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")

    org_user = db.query(OrganizationUser).filter(
        OrganizationUser.organization_id == class_obj.organization_id,
        OrganizationUser.user_id == current_user.id
    ).first()

    if not org_user:
        raise HTTPException(status_code=403, detail="No permission")


    db.delete(group)
    db.commit()

    return {"message": "Group deleted"}