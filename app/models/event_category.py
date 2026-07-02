from sqlalchemy import Column, Integer, ForeignKey
from app.db.database import Base


class EventCategory(Base):
    __tablename__ = "event_categories"

    event_id = Column(
        Integer,
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    category_id = Column(
        Integer,
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    position = Column(Integer, nullable=False, default=0)
