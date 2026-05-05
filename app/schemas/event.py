from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal


class EventCreate(BaseModel):
    organization_id: int
    category_id: Optional[int] = None

    title: str
    description: Optional[str] = None

    min_age: Optional[int] = None
    max_age: Optional[int] = None
    capacity: Optional[int] = None

    image_url: Optional[str] = None
    banner_url: Optional[str] = None

    start_datetime: datetime
    end_datetime: Optional[datetime] = None

    address: Optional[str] = None
    city: Optional[str] = None

    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None


class EventResponse(BaseModel):
    id: int
    organization_id: int
    category_id: Optional[int]

    title: str
    description: Optional[str]

    min_age: Optional[int]
    max_age: Optional[int]
    capacity: Optional[int]

    image_url: Optional[str]
    banner_url: Optional[str]

    start_datetime: datetime
    end_datetime: Optional[datetime]

    address: Optional[str]
    city: Optional[str]

    latitude: Optional[Decimal]
    longitude: Optional[Decimal]

    created_at: datetime
    status: str

    class Config:
        from_attributes = True

class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None

    min_age: Optional[int] = None
    max_age: Optional[int] = None
    capacity: Optional[int] = None

    image_url: Optional[str] = None
    banner_url: Optional[str] = None

    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None

    address: Optional[str] = None
    city: Optional[str] = None

    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None

    status: Optional[str] = None