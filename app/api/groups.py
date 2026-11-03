from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.dependencies import get_db
from app.models.group import Group
from app.schemas.group import GroupCreate, GroupResponse, GroupUpdate
from app.core.auth import get_current_user
from app.core.org_permissions import require_owner_or_admin
from app.models.user import User
from app.models.classes import Class

router = APIRouter(
    prefix="/groups",
    tags=["groups"]
)

_MAX_LIMIT = 500


def _check_permission(org_id: int, current_user: User, db: Session) -> None:
    if current_user.is_system_admin:
        return
    require_owner_or_admin(org_id, current_user.id, db)


@router.get("/", response_model=List[GroupResponse])
def get_groups(
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    limit = min(max(1, limit), _MAX_LIMIT)
    return db.query(Group).offset(offset).limit(limit).all()


@router.post("/", response_model=GroupResponse)
def create_group(
    group: GroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    class_obj = db.query(Class).filter(Class.id == group.class_id).first()

    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")

    _check_permission(class_obj.organization_id, current_user, db)

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

    _check_permission(class_obj.organization_id, current_user, db)

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

    _check_permission(class_obj.organization_id, current_user, db)

    db.delete(group)
    db.commit()

    return {"message": "Group deleted"}