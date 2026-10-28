from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.auth import get_current_user
from app.core.org_permissions import require_owner_or_admin
from app.db.dependencies import get_db
from app.models.classes import Class
from app.models.group import Group
from app.models.group_schedule import GroupSchedule
from app.models.user import User
from app.schemas.group_schedule import GroupScheduleCreate, GroupScheduleResponse, GroupScheduleUpdate

router = APIRouter(
    prefix="/group-schedules",
    tags=["group_schedules"]
)


def _resolve_org_id(group_id: int, db: Session) -> int:
    """Walk GroupSchedule → Group → Class to get the owning organization id."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    class_obj = db.query(Class).filter(Class.id == group.class_id).first()
    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")
    return class_obj.organization_id


def _check_permission(org_id: int, current_user: User, db: Session) -> None:
    """Allow system admins or org owners/admins; reject everyone else."""
    if current_user.is_system_admin:
        return
    require_owner_or_admin(org_id, current_user.id, db)


@router.get("/", response_model=List[GroupScheduleResponse])
def get_group_schedules(db: Session = Depends(get_db)):
    return db.query(GroupSchedule).all()


@router.post("/", response_model=GroupScheduleResponse)
def create_group_schedule(
    schedule: GroupScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _resolve_org_id(schedule.group_id, db)
    _check_permission(org_id, current_user, db)

    new_schedule = GroupSchedule(**schedule.model_dump())
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)
    return new_schedule


@router.get("/group/{group_id}", response_model=List[GroupScheduleResponse])
def get_schedules_by_group(
    group_id: int,
    db: Session = Depends(get_db)
):
    return (
        db.query(GroupSchedule)
        .filter(GroupSchedule.group_id == group_id)
        .all()
    )


@router.put("/{schedule_id}", response_model=GroupScheduleResponse)
def update_group_schedule(
    schedule_id: int,
    schedule_update: GroupScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule = db.query(GroupSchedule).filter(GroupSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    org_id = _resolve_org_id(schedule.group_id, db)
    _check_permission(org_id, current_user, db)

    for key, value in schedule_update.model_dump(exclude_unset=True).items():
        setattr(schedule, key, value)

    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete("/{schedule_id}")
def delete_group_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    schedule = db.query(GroupSchedule).filter(GroupSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    org_id = _resolve_org_id(schedule.group_id, db)
    _check_permission(org_id, current_user, db)

    db.delete(schedule)
    db.commit()
    return {"message": "Schedule deleted"}
