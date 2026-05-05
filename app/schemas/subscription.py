from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SubscriptionCreate(BaseModel):
    organization_id: int
    plan_type: str
    status: Optional[str] = "active"
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class SubscriptionResponse(BaseModel):
    id: int
    organization_id: int
    plan_type: str
    status: str
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class SubscriptionUpdate(BaseModel):
    plan_type: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None