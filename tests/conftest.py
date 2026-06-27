import os

# Must be set before any app module is imported so database.py and security.py
# pick up the values at module-load time.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "pytest-test-secret-key"

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db.database import Base
from app.db.dependencies import get_db
from app.api.organizations import router as org_router
from app.api.organization_invites import router as org_invites_router

# Import every model so that Base.metadata knows all tables and can resolve FKs.
import app.models.category          # noqa: F401
import app.models.classes           # noqa: F401
import app.models.conversation      # noqa: F401
import app.models.event             # noqa: F401
import app.models.favorite          # noqa: F401
import app.models.group             # noqa: F401
import app.models.group_schedule    # noqa: F401
import app.models.message           # noqa: F401
import app.models.notification      # noqa: F401
import app.models.organization      # noqa: F401
import app.models.organization_photo  # noqa: F401
import app.models.organization_user  # noqa: F401
import app.models.payment           # noqa: F401
import app.models.promotion         # noqa: F401
import app.models.review            # noqa: F401
import app.models.review_image      # noqa: F401
import app.models.subscription      # noqa: F401
import app.models.user              # noqa: F401
import app.models.organization_invite_code   # noqa: F401
import app.models.organization_join_request  # noqa: F401

# Minimal app containing only the organizations router — avoids importing
# modules with Python-3.9-only syntax (e.g. upload.py) on this 3.8 runtime.
app = FastAPI()
app.include_router(org_router)
app.include_router(org_invites_router)

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def db(reset_db):
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
