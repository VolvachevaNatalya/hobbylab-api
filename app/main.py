from fastapi import FastAPI
from sqlalchemy import text
from app.db.database import engine
from app.api.auth import router as auth_router
from app.api.me import router as me_router
from app.api.organizations import router as organization_router
from app.api.categories import router as categories_router
from app.api.classes import router as classes_router
from app.api.groups import router as groups_router
from app.api.group_schedules import router as group_schedules_router
from app.api.events import router as events_router
from app.api.favorites import router as favorites_router
from app.api.reviews import router as reviews_router
from app.api.review_images import router as review_images_router
from app.api.conversations import router as conversations_router
from app.api.messages import router as messages_router
from app.api.notifications import router as notification_router
from app.api.promotions import router as promotions_router
from app.api.subscriptions import router as subscriptions_router
from app.api.payments import router as payments_router
from app.api.admin import router as admin_router
from app.api.organization_photos import router as organization_photos_router
from app.api.upload import router as upload_router
from app.db.database import Base
from app.models import *
from app.models.organization_photo import OrganizationPhoto  # noqa: F401 – ensures table is created
Base.metadata.create_all(bind=engine)

# Add columns introduced after initial schema creation
with engine.connect() as _conn:
    _conn.execute(text(
        "ALTER TABLE notifications "
        "ADD COLUMN IF NOT EXISTS conversation_id INTEGER REFERENCES conversations(id)"
    ))
    _conn.commit()

app = FastAPI(swagger_ui_parameters={"persistAuthorization": True})
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(organization_router)
app.include_router(categories_router)
app.include_router(classes_router)
app.include_router(groups_router)
app.include_router(group_schedules_router)
app.include_router(events_router)
app.include_router(favorites_router)
app.include_router(reviews_router)
app.include_router(review_images_router)
app.include_router(conversations_router)
app.include_router(messages_router)
app.include_router(notification_router)
app.include_router(promotions_router)
app.include_router(subscriptions_router)
app.include_router(payments_router)
app.include_router(admin_router)
app.include_router(organization_photos_router)
app.include_router(upload_router)


@app.get("/")
def root():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"db": "connected"}

@app.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}

