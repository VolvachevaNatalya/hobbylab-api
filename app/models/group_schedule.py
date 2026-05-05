from sqlalchemy import Column, Integer, String, ForeignKey, Time
from app.db.database import Base


class GroupSchedule(Base):
    __tablename__ = "group_schedules"

    id = Column(Integer, primary_key=True)

    group_id = Column(
        Integer,
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False
    )

    day_of_week = Column(Integer, nullable=False)

    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    status = Column(String(50), server_default="active")