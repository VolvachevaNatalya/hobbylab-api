from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, field_validator, model_validator

from app.schemas.category import CategoryResponse
from app.schemas.event_series import RecurrenceCreate, RecurrenceResponse


class EventCreate(BaseModel):
    organization_id: int
    # Legacy single-category field — accepted during Flutter migration period.
    # If category_ids is also present, category_ids wins.
    category_id: Optional[int] = None
    category_ids: Optional[List[int]] = None

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
    city_id: Optional[int] = None

    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None

    is_nationwide: bool = False
    price: Optional[float] = None
    price_comment: Optional[str] = None

    recurrence: Optional[RecurrenceCreate] = None

    @model_validator(mode='after')
    def resolve_and_validate_categories(self) -> 'EventCreate':
        if self.category_ids is not None:
            ids = self.category_ids
        elif self.category_id is not None:
            ids = [self.category_id]
        else:
            raise ValueError("Either category_id or category_ids must be provided")
        if len(ids) < 1:
            raise ValueError("At least one category is required")
        if len(ids) > 10:
            raise ValueError("At most 10 categories are allowed")
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate category IDs are not allowed")
        self.category_ids = ids
        return self


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
    city_id: Optional[int] = None
    city_name_he: Optional[str] = None
    city_name_en: Optional[str] = None
    city_name_ru: Optional[str] = None

    latitude: Optional[Decimal]
    longitude: Optional[Decimal]

    is_nationwide: bool = False
    price: Optional[float] = None
    price_comment: Optional[str] = None
    created_at: datetime
    status: str
    distance_km: Optional[float] = None

    # Recurrence fields
    series_id: Optional[int] = None
    occurrence_index: Optional[int] = None
    original_start_datetime: Optional[datetime] = None
    recurrence: Optional[RecurrenceResponse] = None

    # Joined fields
    organization_name: Optional[str] = None
    category_name: Optional[str] = None
    categories: List[CategoryResponse] = []

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
    city_id: Optional[int] = None

    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None

    is_nationwide: Optional[bool] = None
    status: Optional[str] = None
    price: Optional[float] = None
    price_comment: Optional[str] = None
    category_ids: Optional[List[int]] = None
    recurrence: Optional[RecurrenceCreate] = None

    @field_validator("category_ids")
    @classmethod
    def validate_category_ids(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is None:
            return v
        if len(v) < 1:
            raise ValueError("At least one category is required when updating")
        if len(v) > 10:
            raise ValueError("At most 10 categories are allowed")
        if len(set(v)) != len(v):
            raise ValueError("Duplicate category IDs are not allowed")
        return v
