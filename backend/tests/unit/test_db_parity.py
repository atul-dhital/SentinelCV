"""
Unit tests for database setup and SQLite/PostgreSQL parity.

Validates that the test database is correctly configured with all
required tables, columns, and session management.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from db.base import IS_SQLITE, SessionLocal, engine, Base
from sqlalchemy import inspect


class TestDatabaseSetup:
    def test_sqlite_detected_in_tests(self):
        """Test environment should use SQLite."""
        assert IS_SQLITE is True

    def test_session_factory_works(self):
        """Can create and close a session without error."""
        session = SessionLocal()
        try:
            assert session is not None
        finally:
            session.close()

    def test_engine_url_is_test_db(self):
        """Engine should point to the test database, not the production one."""
        url_str = str(engine.url)
        assert "sqlite" in url_str


class TestTablesExist:
    """Verify all critical tables are created in the test database."""

    @pytest.fixture(autouse=True)
    def _inspector(self):
        self.inspector = inspect(engine)
        self.tables = set(self.inspector.get_table_names())

    @pytest.mark.parametrize("table_name", [
        "organizations",
        "users",
        "visitors",
        "face_data",
        "cameras",
        "visitor_logs",
        "audit_logs",
        "refresh_token_sessions",
        "edge_devices",
        "liveness_scores",
        "liveness_challenges",
        "future_enhancements",
        "notifications",
        "webhooks",
    ])
    def test_table_exists(self, table_name):
        assert table_name in self.tables, f"Table '{table_name}' not found in test database"


class TestCriticalColumns:
    """Verify critical columns exist on key tables."""

    @pytest.fixture(autouse=True)
    def _inspector(self):
        self.inspector = inspect(engine)

    def _get_column_names(self, table: str) -> set[str]:
        return {col["name"] for col in self.inspector.get_columns(table)}

    def test_face_data_columns(self):
        cols = self._get_column_names("face_data")
        for expected in ("id", "visitor_id", "embedding", "quality_score", "is_primary"):
            assert expected in cols, f"face_data.{expected} missing"

    def test_visitors_columns(self):
        cols = self._get_column_names("visitors")
        for expected in ("id", "organization_id", "name", "is_known", "is_active"):
            assert expected in cols, f"visitors.{expected} missing"

    def test_users_columns(self):
        cols = self._get_column_names("users")
        for expected in ("id", "organization_id", "email", "password_hash", "role"):
            assert expected in cols, f"users.{expected} missing"

    def test_liveness_scores_columns(self):
        cols = self._get_column_names("liveness_scores")
        for expected in ("id", "organization_id", "is_live", "overall_score", "texture_score"):
            assert expected in cols, f"liveness_scores.{expected} missing"

    def test_face_data_has_face_angle(self):
        """Migration 015 should have added face_angle."""
        cols = self._get_column_names("face_data")
        assert "face_angle" in cols, "face_data.face_angle missing — migration 015 may not have run"


class TestMultiTenantQuery:
    def test_tenant_session_works(self, db, test_org):
        """TenantSession can be configured with a tenant ID."""
        from db.base import TenantSession

        if isinstance(db, TenantSession):
            db.set_tenant(str(test_org.id))
            assert db.tenant_id == str(test_org.id)
        else:
            # Fallback: verify the session at least works
            assert db is not None

    def test_embedding_column_accepts_data(self, db, sample_visitor):
        """Face data embedding column can store and retrieve values."""
        from models.models import FaceData
        import json

        face = FaceData(
            visitor_id=sample_visitor.id,
            embedding=json.dumps([0.1] * 512),
            image_url="/static/test.jpg",
            quality_score=0.9,
            is_primary=True,
        )
        db.add(face)
        db.commit()
        db.refresh(face)

        assert face.id is not None
        assert face.embedding is not None

        # Clean up
        db.delete(face)
        db.commit()
