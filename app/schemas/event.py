import json
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.category import CategoryResponse
from app.schemas.event_series import RecurrenceCreate, RecurrenceResponse

# ── Age-group definitions ─────────────────────────────────────────────────────
# Canonical mapping from group key → (min_inclusive, max_inclusive).
# "custom" has no fixed range — it delegates to Event.min_age / Event.max_age.

VALID_AGE_GROUPS = frozenset({"toddlers", "kids", "teens", "adults", "family", "custom"})

AGE_GROUP_RANGES: Dict[str, Tuple[int, int]] = {
    "toddlers": (2, 5),
    "kids":     (6, 11),
    "teens":    (12, 17),
    "adults":   (18, 120),
    "family":   (0, 120),
}


def _validate_age_groups_list(groups: List[str]) -> List[str]:
    invalid = [g for g in groups if g not in VALID_AGE_GROUPS]
    if invalid:
        raise ValueError(f"Unknown age groups: {invalid}. Allowed: {sorted(VALID_AGE_GROUPS)}")
    if len(set(groups)) != len(groups):
        raise ValueError("Duplicate age groups are not allowed")
    return groups


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
    age_groups: Optional[List[str]] = None

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
        # ── Category resolution ───────────────────────────────────────────────
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

        # ── Age groups validation ─────────────────────────────────────────────
        if self.age_groups is not None:
            if len(self.age_groups) == 0:
                self.age_groups = None  # treat empty as absent
            else:
                self.age_groups = _validate_age_groups_list(self.age_groups)
                if "custom" in self.age_groups:
                    if self.min_age is not None and not (0 <= self.min_age <= 120):
                        raise ValueError("min_age must be between 0 and 120")
                    if self.max_age is not None and not (0 <= self.max_age <= 120):
                        raise ValueError("max_age must be between 0 and 120")
                    if (self.min_age is not None and self.max_age is not None
                            and self.min_age > self.max_age):
                        raise ValueError("min_age must be <= max_age for custom age group")

        return self


class EventResponse(BaseModel):
    id: int
    organization_id: int
    category_id: Optional[int]

    title: str
    description: Optional[str]

    min_age: Optional[int]
    max_age: Optional[int]
    age_groups: Optional[List[str]] = None

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

    # Computed
    is_past: bool = False

    @field_validator("age_groups", mode="before")
    @classmethod
    def parse_age_groups(cls, v):
        """Deserialize JSON string from TEXT column back to a Python list."""
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    class Config:
        from_attributes = True


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None

    min_age: Optional[int] = None
    max_age: Optional[int] = None
    age_groups: Optional[List[str]] = None

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

    @model_validator(mode='after')
    def validate_age_groups_and_custom_range(self) -> 'EventUpdate':
        if self.age_groups is None:
            return self
        if len(self.age_groups) == 0:
            self.age_groups = None
            return self
        self.age_groups = _validate_age_groups_list(self.age_groups)
        if "custom" in self.age_groups:
            if self.min_age is not None and not (0 <= self.min_age <= 120):
                raise ValueError("min_age must be between 0 and 120")
            if self.max_age is not None and not (0 <= self.max_age <= 120):
                raise ValueError("max_age must be between 0 and 120")
            if (self.min_age is not None and self.max_age is not None
                    and self.min_age > self.max_age):
                raise ValueError("min_age must be <= max_age for custom age group")
        return self
