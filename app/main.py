import logging
from fastapi import FastAPI
from sqlalchemy import text
from app.db.database import engine

_logger = logging.getLogger(__name__)
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
from app.api.organization_invites import router as organization_invites_router, resolve_router as invite_resolve_router
from app.api.organization_members import router as organization_members_router
from app.api.cities import router as cities_router
from app.api.upload import router as upload_router
from app.api.support import router as support_router
from app.api.providers import router as providers_router
from app.db.database import Base
from app.models import *
from app.models.user_auth_provider import UserAuthProvider  # noqa: F401 – ensures table is created
from app.models.organization_photo import OrganizationPhoto  # noqa: F401 – ensures table is created
from app.models.organization_invite_code import OrganizationInviteCode  # noqa: F401 – ensures table is created
from app.models.organization_join_request import OrganizationJoinRequest  # noqa: F401 – ensures table is created
from app.models.event_category import EventCategory  # noqa: F401 – ensures table is created
from app.models.organization_category import OrganizationCategory  # noqa: F401 – ensures table is created
from app.models.city import City  # noqa: F401 – ensures table is created
from app.models.event_series import EventSeries  # noqa: F401 – ensures table is created
Base.metadata.create_all(bind=engine)

# Add columns introduced after initial schema creation
with engine.connect() as _conn:
    _conn.execute(text(
        "ALTER TABLE notifications "
        "ADD COLUMN IF NOT EXISTS conversation_id INTEGER REFERENCES conversations(id)"
    ))
    _conn.execute(text(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0"
    ))
    _conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS notif_appointments BOOLEAN NOT NULL DEFAULT TRUE"
    ))
    _conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS notif_chat BOOLEAN NOT NULL DEFAULT TRUE"
    ))
    _conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS notif_activity BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    _conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS notif_offers BOOLEAN NOT NULL DEFAULT TRUE"
    ))
    _conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS provider VARCHAR(50)"
    ))
    _conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS provider_user_id VARCHAR(255)"
    ))
    _conn.execute(text("""
        CREATE TABLE IF NOT EXISTS user_auth_providers (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR NOT NULL,
            provider_user_id VARCHAR NOT NULL,
            provider_email VARCHAR,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_provider_user_id UNIQUE (provider, provider_user_id),
            CONSTRAINT uq_user_provider UNIQUE (user_id, provider)
        )
    """))
    # Detect conflicting legacy identities before migrating (non-destructive: log only)
    _conflicts = _conn.execute(text("""
        SELECT u.id, u.email, u.provider, u.provider_user_id
        FROM users u
        JOIN user_auth_providers uap
          ON uap.provider = u.provider
         AND uap.provider_user_id = u.provider_user_id
         AND uap.user_id != u.id
        WHERE u.password_hash IS NULL
          AND u.provider IS NOT NULL
          AND u.provider_user_id IS NOT NULL
    """)).fetchall()
    for _row in _conflicts:
        _logger.warning(
            "migration_identity_conflict | user_id=%s email=%s provider=%s provider_user_id=%s",
            _row[0], _row[1], _row[2], _row[3],
        )

    _conn.execute(text("""
        INSERT INTO user_auth_providers (user_id, provider, provider_user_id, provider_email, created_at)
        SELECT id, provider, provider_user_id, email, NOW()
        FROM users
        WHERE password_hash IS NULL
          AND provider IS NOT NULL
          AND provider_user_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """))
    _conn.commit()

app = FastAPI()



from fastapi.middleware.cors import CORSMiddleware
from app.core.config import parse_cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_cors_origins(),
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
app.include_router(organization_invites_router)
app.include_router(invite_resolve_router)
app.include_router(organization_members_router)
app.include_router(cities_router)
app.include_router(upload_router)
app.include_router(support_router)
app.include_router(providers_router)


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

