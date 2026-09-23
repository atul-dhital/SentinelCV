"""
Shared test fixtures for SentinelCV backend tests.

Provides:
- Test database (shared in-memory SQLite)
- FastAPI TestClient
- Pre-authenticated user fixtures (admin, staff)
- Sample data fixtures (visitor, camera, etc.)
"""

import os
import sys
import shutil
import pytest
from pathlib import Path
from typing import Generator
from uuid import uuid4

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

# Force SQLite for tests with a shared in-memory database so runs avoid local
# filesystem quirks and remain stable on Windows.
TEST_RUNTIME_ROOT = Path(

    os.getenv(
        "SENTINELCV_TEST_RUNTIME_DIR",
        Path(__file__).resolve().parent.parent / ".test_runtime",
    )
).resolve()
TEST_DB_DIR = (TEST_RUNTIME_ROOT / f"run-{uuid4().hex}").resolve()
TEST_DB_URL = "sqlite://"
TEST_DATA_DIR = TEST_DB_DIR / "data"
TEST_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["AUTO_INIT_DB"] = "0"
os.environ["DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
# Disable rate limiting in tests by setting very high limits
os.environ["AUTH_LOGIN_IP_LIMIT"] = "500"
os.environ["AUTH_LOGIN_EMAIL_LIMIT"] = "500"
os.environ["AUTH_REFRESH_IP_LIMIT"] = "500"
os.environ["AUTH_FORGOT_PASSWORD_IP_LIMIT"] = "500"
os.environ["AUTH_FORGOT_PASSWORD_EMAIL_LIMIT"] = "500"
os.environ["AUTH_RESET_PASSWORD_IP_LIMIT"] = "500"
os.environ["AUTH_REGISTER_IP_LIMIT"] = "500"
os.environ.setdefault("EMBEDDING_KEY_SECRET", "sentinelcv-test-embedding-secret-key-change")
# Tests use private RTSP targets (192.168.x.x) and synthetic biometric
# inputs. Production code rejects both by default; the integration suite
# opts into the relaxed behaviour explicitly — but only in the "full"
# profile (default, matches existing CI). SENTINELCV_TEST_PROFILE=core
# forces all four bypasses off so security/tenant suites can prove they
# hold up without synthetic fallback or experimental routers propping
# them up. A release must never treat the full/synthetic profile as
# proof of biometric correctness (see docs/qa/GAP_REGISTER.md P0-03).
_TEST_PROFILE = os.getenv("SENTINELCV_TEST_PROFILE", "full").strip().lower()
if _TEST_PROFILE == "core":
    os.environ.setdefault("ALLOW_PRIVATE_RTSP_TARGETS", "0")
    os.environ.setdefault("ALLOW_SYNTHETIC_BIOMETRIC_FALLBACK", "0")
    os.environ.setdefault("SKIP_USER_PATH_EXISTS_CHECK", "0")
    os.environ.setdefault("ENABLE_EXPERIMENTAL_FEATURES", "0")
    os.environ.setdefault("ENABLE_PHASE3_FEATURES", "0")
else:
    os.environ.setdefault("ALLOW_PRIVATE_RTSP_TARGETS", "1")
    os.environ.setdefault("ALLOW_SYNTHETIC_BIOMETRIC_FALLBACK", "1")
    os.environ.setdefault("SKIP_USER_PATH_EXISTS_CHECK", "1")
    # Mount all experimental and Phase-3 routers so pre-existing tests can run.
    # Production gating (ENABLE_EXPERIMENTAL_FEATURES=0) is verified separately
    # by the CI production-env-check job and test_phase2_security.py.
    os.environ.setdefault("ENABLE_EXPERIMENTAL_FEATURES", "1")
    os.environ.setdefault("ENABLE_PHASE3_FEATURES", "1")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.base as db_base

test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Enable FK support for SQLite
@event.listens_for(test_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
db_base.engine = test_engine
db_base.SessionLocal = TestSessionLocal

import main as main_module
main_module.engine = test_engine
main_module.SessionLocal = TestSessionLocal

from db.base import Base, get_db
from main import app
from core.security import hash_password
from models.models import Organization, User, Visitor, Camera, FaceData


def pytest_collection_modifyitems(config, items):
    """Auto-apply unit/integration/security/tenant markers from file location
    and name so the existing suite is queryable via `-m` without hand-editing
    every test file. Best-effort: narrower than a manual audit, but gives an
    immediate `pytest -m security` / `-m tenant` slice."""
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        name = item.name.lower()
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)
        if "security" in path or "security" in name:
            item.add_marker(pytest.mark.security)
        if "tenant" in path or "tenant" in name or "cross_org" in name or "other_org" in name:
            item.add_marker(pytest.mark.tenant)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session", autouse=True)
def create_test_db():
    """Create test database tables once per test session."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    shutil.rmtree(TEST_DB_DIR, ignore_errors=True)


@pytest.fixture
def db() -> Generator:
    """Provide a clean database session for each test."""
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        
        # Clear all data from all tables for next test using raw SQL
        # This ensures test isolation by removing data created in this test
        try:
            from sqlalchemy import text, inspect
            session = TestSessionLocal()
            inspector = inspect(test_engine)
            
            # Disable foreign key constraints temporarily
            session.execute(text("PRAGMA foreign_keys=OFF"))
            
            # Get table names and delete in reverse order
            table_names = reversed(inspector.get_table_names())
            for table_name in table_names:
                session.execute(text(f"DELETE FROM {table_name}"))
            
            # Re-enable foreign key constraints
            session.execute(text("PRAGMA foreign_keys=ON"))
            session.commit()
            session.close()
        except Exception as cleanup_error:
            # Log but don't fail if cleanup has issues
            pass


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    """Clear in-memory rate-limit state between tests so logins aren't throttled."""
    yield
    try:
        from services.redis_service import get_redis_service
        svc = get_redis_service()
        if hasattr(svc, "_fallback") and hasattr(svc._fallback, "_data"):
            svc._fallback._data.clear()
            svc._fallback._expiry.clear()
    except Exception:
        pass


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def test_org(db) -> Organization:
    """Create a test organization."""
    org = Organization(name="Test Organization", face_confidence_threshold=0.6)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture
def admin_user(db, test_org) -> User:
    """Create an admin test user."""
    existing = db.query(User).filter(User.email == "admin@test.com").first()
    if existing:
        return existing
    user = User(
        organization_id=test_org.id,
        email="admin@test.com",
        full_name="Test Admin",
        password_hash=hash_password("Admin123!"),
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def staff_user(db, test_org) -> User:
    """Create a staff test user."""
    existing = db.query(User).filter(User.email == "staff@test.com").first()
    if existing:
        return existing
    user = User(
        organization_id=test_org.id,
        email="staff@test.com",
        full_name="Test Staff",
        password_hash=hash_password("Staff123!"),
        role="staff",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_headers(client, admin_user) -> dict:
    """Get auth headers for admin user."""
    response = client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": "Admin123!",
    })
    token = response.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def staff_headers(client, staff_user) -> dict:
    """Get auth headers for staff user."""
    response = client.post("/api/v1/auth/login", json={
        "email": "staff@test.com",
        "password": "Staff123!",
    })
    token = response.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_visitor(db, test_org) -> Visitor:
    """Create a sample visitor."""
    visitor = Visitor(
        organization_id=test_org.id,
        name="John Doe",
        email="john@example.com",
        phone="+1234567890",
        description="Test visitor",
        is_known=True,
        is_active=True,
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)
    return visitor


@pytest.fixture
def sample_camera(db, test_org) -> Camera:
    """Create a sample camera."""
    camera = Camera(
        organization_id=test_org.id,
        name="Front Door Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        location="Main Entrance",
        is_active=True,
        status="online",
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera
