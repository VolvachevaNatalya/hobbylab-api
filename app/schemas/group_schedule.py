from pydantic import BaseModel
from typing import Optional
from datetime import time


class GroupScheduleCreate(BaseModel):
    group_id: int
    day_of_week: int
    start_time: time
    end_time: time


class GroupScheduleResponse(BaseModel):
    id: int
    group_id: int
    day_of_week: int
    start_time: time
    end_time: time
    status: str

    class Config:
        from_attributes = True

class GroupScheduleUpdate(BaseModel):
    day_of_week: Optional[int] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    status: Optional[str] = None