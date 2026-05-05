from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.dependencies import get_db
from app.models.group_schedule import GroupSchedule
from app.schemas.group_schedule import GroupScheduleCreate, GroupScheduleResponse, GroupScheduleUpdate

router = APIRouter(
    prefix="/group-schedules",
    tags=["group_schedules"]
)


@router.get("/", response_model=List[GroupScheduleResponse])
def get_group_schedules(db: Session = Depends(get_db)):
    return db.query(GroupSchedule).all()


@router.post("/", response_model=GroupScheduleResponse)
def create_group_schedule(
    schedule: GroupScheduleCreate,
    db: Session = Depends(get_db)
):
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
    schedules = (
        db.query(GroupSchedule)
        .filter(GroupSchedule.group_id == group_id)
        .all()
    )

    return schedules


@router.put("/{schedule_id}", response_model=GroupScheduleResponse)
def update_group_schedule(
    schedule_id: int,
    schedule_update: GroupScheduleUpdate,
    db: Session = Depends(get_db)
):
    schedule = db.query(GroupSchedule).filter(GroupSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    for key, value in schedule_update.model_dump(exclude_unset=True).items():
        setattr(schedule, key, value)

    db.commit()
    db.refresh(schedule)

    return schedule

@router.delete("/{schedule_id}")
def delete_group_schedule(
    schedule_id: int,
    db: Session = Depends(get_db)
):
    schedule = db.query(GroupSchedule).filter(GroupSchedule.id == schedule_id).first()

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    db.delete(schedule)
    db.commit()

    return {"message": "Schedule deleted"}