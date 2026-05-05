from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PromotionCreate(BaseModel):
    organization_id: int
    event_id: Optional[int] = None
    promotion_type: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class PromotionResponse(BaseModel):
    id: int
    organization_id: int
    event_id: Optional[int]
    promotion_type: str
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class PromotionUpdate(BaseModel):
    event_id: Optional[int] = None
    promotion_type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None