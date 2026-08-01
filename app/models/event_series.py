from sqlalchemy import Column, Date, DateTime, Integer, String
from sqlalchemy.sql import func

from app.db.database import Base


class EventSeries(Base):
    __tablename__ = "event_series"

    id = Column(Integer, primary_key=True)
    frequency = Column(String(20), nullable=False)
    interval = Column(Integer, nullable=False, default=1)
    end_type = Column(String(10), nullable=False)
    total_count = Column(Integer, nullable=True)
    end_date = Column(Date, nullable=True)
    generated_until = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, server_default="active")
    created_at = Column(DateTime, server_default=func.now())
