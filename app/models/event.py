from sqlalchemy import Boolean, Column, Integer, String, Text, ForeignKey, DateTime, DECIMAL
from sqlalchemy.sql import func
from app.db.database import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)

    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False
    )

    category_id = Column(
        Integer,
        ForeignKey("categories.id")
    )

    title = Column(String(255), nullable=False)
    description = Column(Text)

    min_age = Column(Integer)
    max_age = Column(Integer)
    capacity = Column(Integer)

    image_url = Column(Text)
    banner_url = Column(Text)

    start_datetime = Column(DateTime, nullable=False)
    end_datetime = Column(DateTime)

    address = Column(Text)
    city = Column(String(100))

    latitude = Column(DECIMAL(10, 8))
    longitude = Column(DECIMAL(11, 8))

    is_nationwide = Column(Boolean, server_default="false", default=False)

    created_at = Column(DateTime, server_default=func.now())

    status = Column(String(50), server_default="active")