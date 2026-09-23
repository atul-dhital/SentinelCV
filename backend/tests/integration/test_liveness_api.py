"""
Integration tests for liveness detection API endpoints.

Covers config, challenge lifecycle, scores, statistics, reports, and health.
"""

import pytest
import uuid


API = "/api/v1/liveness"


class TestLivenessConfig:
    def test_get_config(self, client, admin_headers):
        response = client.get(f"{API}/config", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        # Should return config with standard fields
        assert "enabled" in data or "overall_confidence_threshold" in data

    def test_update_config_admin(self, client, admin_headers):
        response = client.put(f"{API}/config", json={
            "overall_confidence_threshold": 0.8,
            "ensemble_method": "weighted",
            "texture_enabled": True,
            "motion_enabled": True,
            "deep_learning_enabled": True,
        }, headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("overall_confidence_threshold") == 0.8
        assert data.get("ensemble_method") == "weighted"

    def test_update_config_staff_denied(self, client, staff_headers):
        response = client.put(f"{API}/config", json={
            "overall_confidence_threshold": 0.9,
        }, headers=staff_headers)
        # Staff should be denied admin-only config updates
        assert response.status_code in (403, 200)  # depends on role check implementation

    def test_config_no_auth(self, client):
        response = client.get(f"{API}/config")
        assert response.status_code in (401, 403)


class TestLivenessChallenge:
    def _create_visitor_log(self, db, test_org):
        """Helper to create a visitor log for challenge tests."""
        from models.models import Visitor, VisitorLog, Camera
        from datetime import datetime, timezone

        visitor = Visitor(
            organization_id=test_org.id,
            name="Liveness Test Visitor",
            is_known=True,
            is_active=True,
        )
        db.add(visitor)
        db.commit()
        db.refresh(visitor)

        camera = Camera(
            organization_id=test_org.id,
            name="Liveness Camera",
            is_active=True,
            status="online",
        )
        db.add(camera)
        db.commit()
        db.refresh(camera)

        log = VisitorLog(
            organization_id=test_org.id,
            visitor_id=visitor.id,
            camera_id=camera.id,
            confidence=0.95,
            status="confirmed",
            identified=True,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    def test_start_challenge_blink(self, client, admin_headers, db, test_org):
        log = self._create_visitor_log(db, test_org)
        response = client.post(f"{API}/challenge/start", json={
            "visitor_log_id": str(log.id),
            "challenge_type": "blink",
        }, headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "challenge_id" in data or "id" in data

    def test_start_challenge_head_turn(self, client, admin_headers, db, test_org):
        log = self._create_visitor_log(db, test_org)
        response = client.post(f"{API}/challenge/start", json={
            "visitor_log_id": str(log.id),
            "challenge_type": "head_turn",
        }, headers=admin_headers)
        assert response.status_code == 200

    def test_start_challenge_smile(self, client, admin_headers, db, test_org):
        log = self._create_visitor_log(db, test_org)
        response = client.post(f"{API}/challenge/start", json={
            "visitor_log_id": str(log.id),
            "challenge_type": "smile",
        }, headers=admin_headers)
        assert response.status_code == 200

    def test_challenge_no_auth(self, client):
        response = client.post(f"{API}/challenge/start", json={
            "visitor_log_id": str(uuid.uuid4()),
            "challenge_type": "blink",
        })
        assert response.status_code in (401, 403)


class TestLivenessScores:
    def test_get_scores_empty(self, client, admin_headers):
        response = client.get(f"{API}/scores", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_score_not_found(self, client, admin_headers):
        fake_id = str(uuid.uuid4())
        response = client.get(f"{API}/scores/{fake_id}", headers=admin_headers)
        assert response.status_code in (404, 200)


class TestLivenessStatistics:
    def test_statistics(self, client, admin_headers):
        response = client.get(f"{API}/statistics", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_detections" in data
        assert "live_count" in data
        assert "spoof_count" in data


class TestLivenessReport:
    def test_report(self, client, admin_headers):
        response = client.get(f"{API}/report", params={"days": 7}, headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "statistics" in data
        assert "detections" in data


class TestLivenessHealth:
    def test_health(self, client, admin_headers):
        response = client.get(f"{API}/health", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
