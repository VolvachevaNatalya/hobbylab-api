from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, model_validator

_VALID_FREQUENCIES = {"daily", "weekly", "monthly", "yearly"}
_VALID_END_TYPES = {"count", "date", "never"}


class RecurrenceCreate(BaseModel):
    frequency: str
    interval: int = 1
    end_type: str
    total_count: Optional[int] = None
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_fields(self) -> "RecurrenceCreate":
        if self.frequency not in _VALID_FREQUENCIES:
            raise ValueError(f"frequency must be one of: {', '.join(sorted(_VALID_FREQUENCIES))}")
        if self.interval < 1:
            raise ValueError("interval must be >= 1")
        if self.end_type not in _VALID_END_TYPES:
            raise ValueError(f"end_type must be one of: {', '.join(sorted(_VALID_END_TYPES))}")
        if self.end_type == "count":
            if self.total_count is None or self.total_count < 2:
                raise ValueError("total_count must be >= 2 when end_type is 'count'")
        if self.end_type == "date":
            if self.end_date is None:
                raise ValueError("end_date is required when end_type is 'date'")
        return self


class RecurrenceResponse(BaseModel):
    id: int
    frequency: str
    interval: int
    end_type: str
    total_count: Optional[int]
    end_date: Optional[date]
    generated_until: Optional[datetime]
    status: str

    class Config:
        from_attributes = True
