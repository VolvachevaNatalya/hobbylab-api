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
from app.api.organization_invites import router as organization_invites_router, resolve_router as invite_resolve_router
from app.api.organization_members import router as organization_members_router
from app.api.upload import router as upload_router
from app.db.database import Base
from app.models import *
from app.models.organization_photo import OrganizationPhoto  # noqa: F401 – ensures table is created
from app.models.organization_invite_code import OrganizationInviteCode  # noqa: F401 – ensures table is created
from app.models.organization_join_request import OrganizationJoinRequest  # noqa: F401 – ensures table is created
Base.metadata.create_all(bind=engine)

# Add columns introduced after initial schema creation
with engine.connect() as _conn:
    _conn.execute(text(
        "ALTER TABLE notifications "
        "ADD COLUMN IF NOT EXISTS conversation_id INTEGER REFERENCES conversations(id)"
    ))
    _conn.commit()

app = FastAPI(swagger_ui_parameters={"persistAuthorization": True})


import os
import base64
import requests

@app.get("/debug-webdav")
def debug_webdav():
    url = "https://static.hobbylab.co.il/upload/"

    username = os.getenv("WEBDAV_USERNAME")
    password = os.getenv("WEBDAV_PASSWORD")

    if not username or not password:
        return {
            "error": "WEBDAV_USERNAME or WEBDAV_PASSWORD is missing",
            "username_exists": bool(username),
            "password_exists": bool(password),
        }

    results = {}

    for method in ["HEAD", "OPTIONS", "PROPFIND"]:
        try:
            headers = {}
            if method == "PROPFIND":
                headers["Depth"] = "0"

            r = requests.request(
                method,
                url,
                auth=(username, password),
                headers=headers,
                timeout=20,
            )

            results[method] = {
                "status": r.status_code,
                "reason": r.reason,
                "text": r.text[:300],
            }

        except Exception as e:
            results[method] = {
                "error": str(e)
            }

    token = base64.b64encode(f"{username}:{password}".encode()).decode()

    try:
        r = requests.request(
            "PROPFIND",
            url,
            headers={
                "Authorization": f"Basic {token}",
                "Depth": "0",
            },
            timeout=20,
        )

        results["manual_basic"] = {
            "status": r.status_code,
            "reason": r.reason,
            "text": r.text[:300],
        }

    except Exception as e:
        results["manual_basic"] = {
            "error": str(e)
        }

    return {
        "username_exists": True,
        "password_exists": True,
        "username_length": len(username),
        "password_length": len(password),
        "username_has_spaces": username != username.strip(),
        "password_has_spaces": password != password.strip(),
        "results": results,
    }


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
app.include_router(organization_invites_router)
app.include_router(invite_resolve_router)
app.include_router(organization_members_router)
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

