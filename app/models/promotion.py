from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base


class Promotion(Base):
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"))

    promotion_type = Column(String(50))

    start_date = Column(DateTime)
    end_date = Column(DateTime)

    created_at = Column(DateTime(timezone=True), server_default=func.now())