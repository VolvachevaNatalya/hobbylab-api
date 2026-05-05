from pydantic import BaseModel
from typing import Optional


class ClassSearchParams(BaseModel):
    category_id: Optional[int] = None
    city: Optional[str] = None
    age: Optional[int] = None
    day_of_week: Optional[int] = None

    min_price: Optional[float] = None
    max_price: Optional[float] = None
    price_type: Optional[str] = None

    limit: int = 20
    offset: int = 0