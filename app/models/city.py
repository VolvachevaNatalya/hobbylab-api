from sqlalchemy import Boolean, Column, Float, Integer, String
from app.db.database import Base


class City(Base):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True)
    name_he = Column(String(100), nullable=False)
    name_en = Column(String(100), nullable=False)
    name_ru = Column(String(100), nullable=False)
    latitude = Column(Float)
    longitude = Column(Float)
    is_active = Column(Boolean, nullable=False, default=True)
