"""
Tests for Phase 3 Advanced Recognition API Endpoints

Covers endpoints for:
- Multi-angle recognition
- Cross-camera ReID
- Emotion/Action detection
- Unified recognition
- Health check
"""

import pytest
from concurrent.futures import ThreadPoolExecutor

from api.advanced_recognition import reset_runtime_state
from models.models import Camera, CrossCameraMovementSummary, FaceData, Visitor

BASE = "/api/v1/recognition/advanced"


@pytest.fixture(autouse=True)
def reset_advanced_recognition_runtime():
    reset_runtime_state()
    yield
    reset_runtime_state()


class TestMultiAngleEndpoints:

    def test_register_multi_angle_valid(self, client, admin_headers):
        payload = {
            "visitor_id": "visitor_123",
            "angle_data": [
                {"angle_name": "frontal", "yaw": 0.0, "pitch": 0.0},
                {"angle_name": "profile", "yaw": -70.0, "pitch": 0.0},
            ],
            "threshold": 0.60,
        }
        response = client.post(
            f"{BASE}/multi-angle/register", json=payload, headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["visitor_id"] == "visitor_123"
        assert "completeness" in data
        assert data["angles_processed"] == 2

    def test_register_multi_angle_missing_visitor_id(self, client, admin_headers):
        payload = {
            "angle_data": [{"angle_name": "frontal", "yaw": 0.0, "pitch": 0.0}],
        }
        response = client.post(
            f"{BASE}/multi-angle/register", json=payload, headers=admin_headers
        )
        assert response.status_code == 422

    def test_register_multi_angle_empty_angles(self, client, admin_headers):
        payload = {
            "visitor_id": "visitor_123",
            "angle_data": [],
        }
        response = client.post(
            f"{BASE}/multi-angle/register", json=payload, headers=admin_headers
        )
        # Empty angle_data still succeeds with 0 completeness
        assert response.status_code in [200, 400]

    def test_get_multi_angle_stats(self, client, admin_headers):
        response = client.get(f"{BASE}/multi-angle/stats", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_visitors" in data
        assert "average_completeness" in data

    def test_multi_angle_stats_reflect_registered_embeddings(self, client, admin_headers):
        registrations = [
            {
                "visitor_id": "visitor_alpha",
                "angle_data": [
                    {"angle_name": "frontal", "yaw": 0.0, "pitch": 0.0},
                    {"angle_name": "profile_left", "yaw": -70.0, "pitch": 0.0},
                ],
            },
            {
                "visitor_id": "visitor_beta",
                "angle_data": [
                    {"angle_name": "frontal", "yaw": 0.0, "pitch": 0.0},
                    {"angle_name": "45_right", "yaw": 38.0, "pitch": 0.0},
                    {"angle_name": "45_left", "yaw": -36.0, "pitch": 0.0},
                ],
            },
        ]
        for payload in registrations:
            response = client.post(
                f"{BASE}/multi-angle/register", json=payload, headers=admin_headers
            )
            assert response.status_code == 200

        stats = client.get(f"{BASE}/multi-angle/stats", headers=admin_headers)
        assert stats.status_code == 200
        data = stats.json()
        assert data["total_visitors"] == 2
        assert set(data["registered_visitors"]) == {"visitor_alpha", "visitor_beta"}
        assert data["angle_distribution"]["frontal"] >= 2

    def test_get_multi_angle_stats_no_auth(self, client):
        response = client.get(f"{BASE}/multi-angle/stats")
        assert response.status_code in [401, 403]

    def test_register_multi_angle_persists_face_data_for_real_visitor(
        self,
        client,
        admin_headers,
        admin_user,
        db,
    ):
        visitor = Visitor(
            organization_id=admin_user.organization_id,
            name="Multi Angle Visitor",
            is_known=True,
            is_active=True,
        )
        db.add(visitor)
        db.commit()
        db.refresh(visitor)

        response = client.post(
            f"{BASE}/multi-angle/register",
            json={
                "visitor_id": str(visitor.id),
                "angle_data": [
                    {"angle_name": "frontal", "yaw": 0.0, "pitch": 0.0},
                    {"angle_name": "45_left", "yaw": -42.0, "pitch": 0.0},
                ],
            },
            headers=admin_headers,
        )
        assert response.status_code == 200

        db.expire_all()
        rows = db.query(FaceData).filter(FaceData.visitor_id == visitor.id).all()
        assert len(rows) >= 2
        assert {"frontal", "45_left"}.issubset({row.face_angle for row in rows})


class TestCrossCameraREIDEndpoints:

    def test_reid_identify_valid(self, client, admin_headers):
        payload = {
            "embedding": [0.1] * 128,
            "current_camera": "entrance",
            "use_temporal": True,
        }
        response = client.post(
            f"{BASE}/reid/identify", json=payload, headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "confidence" in data
        assert "camera" in data

    def test_reid_identify_missing_camera(self, client, admin_headers):
        payload = {
            "embedding": [0.1] * 128,
        }
        response = client.post(
            f"{BASE}/reid/identify", json=payload, headers=admin_headers
        )
        assert response.status_code == 422

    def test_reid_track_visitor(self, client, admin_headers):
        response = client.get(
            f"{BASE}/reid/track/visitor_123", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["visitor_id"] == "visitor_123"
        assert "recent_path" in data
        assert "predicted_next_camera" in data

    def test_reid_track_unknown_visitor(self, client, admin_headers):
        response = client.get(
            f"{BASE}/reid/track/unknown_xyz", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["visitor_id"] == "unknown_xyz"

    def test_reid_get_cameras(self, client):
        response = client.get(f"{BASE}/cameras")
        assert response.status_code == 200
        data = response.json()
        assert "cameras" in data
        assert len(data["cameras"]) >= 1
        assert "camera_id" in data["cameras"][0]

    def test_reid_identify_matches_persisted_gallery_visitor(
        self,
        client,
        admin_headers,
        admin_user,
        db,
    ):
        visitor = Visitor(
            organization_id=admin_user.organization_id,
            name="ReID Visitor",
            is_known=True,
            is_active=True,
        )
        db.add(visitor)
        db.commit()
        db.refresh(visitor)

        db.add(
            FaceData(
                visitor_id=visitor.id,
                embedding=[0.2] * 512,
                quality_score=0.92,
                face_angle="frontal",
                is_primary=True,
            )
        )
        db.commit()

        response = client.post(
            f"{BASE}/reid/identify",
            json={
                "embedding": [0.2] * 512,
                "current_camera": "entrance",
                "use_temporal": True,
            },
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["visitor_id"] == str(visitor.id)
        assert data["confidence"] >= 0.62


class TestEmotionDetectionEndpoints:

    def test_detect_emotion_no_data(self, client, admin_headers):
        response = client.post(f"{BASE}/emotion/detect", headers=admin_headers)
        assert response.status_code in [200, 400, 422]

    def test_get_emotion_history(self, client, admin_headers):
        response = client.get(
            f"{BASE}/emotion/history/visitor_123", headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["visitor_id"] == "visitor_123"
        assert "emotions" in data

    def test_get_emotion_history_custom_window(self, client, admin_headers):
        response = client.get(
            f"{BASE}/emotion/history/visitor_123?window_seconds=600",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["window_seconds"] == 600

    def test_get_emotion_history_no_auth(self, client):
        response = client.get(f"{BASE}/emotion/history/visitor_123")
        assert response.status_code in [401, 403]


class TestUnifiedRecognitionEndpoint:

    def test_unified_recognize_with_embedding(self, client, admin_headers):
        payload = {
            "embedding": [0.1] * 768,
            "camera_id": "entrance",
            "include_emotion": True,
            "include_behavior": True,
        }
        response = client.post(
            f"{BASE}/recognize", json=payload, headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "combined_confidence" in data

    def test_unified_recognize_minimal(self, client, admin_headers):
        payload = {
            "embedding": [0.1] * 768,
            "camera_id": "lobby",
        }
        response = client.post(
            f"{BASE}/recognize", json=payload, headers=admin_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "combined_confidence" in data

    def test_unified_recognize_missing_fields(self, client, admin_headers):
        payload = {"embedding": [0.1] * 768}
        response = client.post(
            f"{BASE}/recognize", json=payload, headers=admin_headers
        )
        assert response.status_code == 422

    def test_unified_recognize_no_auth(self, client):
        payload = {"embedding": [0.1] * 768, "camera_id": "entrance"}
        response = client.post(f"{BASE}/recognize", json=payload)
        assert response.status_code in [401, 403]

    def test_unified_recognize_records_emotion_and_camera_history(self, client, admin_headers):
        visitor_id = "visitor_history"
        response = client.post(
            f"{BASE}/recognize",
            json={
                "embedding": [0.15] * 768,
                "camera_id": "entrance",
                "visitor_id": visitor_id,
                "include_emotion": True,
            },
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["visitor_id"] == visitor_id

        emotion_history = client.get(
            f"{BASE}/emotion/history/{visitor_id}", headers=admin_headers
        )
        assert emotion_history.status_code == 200
        emotion_data = emotion_history.json()
        assert emotion_data["average_emotion"] is not None
        assert len(emotion_data["recent_events"]) >= 1

        track = client.get(f"{BASE}/reid/track/{visitor_id}", headers=admin_headers)
        assert track.status_code == 200
        track_data = track.json()
        assert len(track_data["recent_path"]) >= 1

    def test_unified_recognize_persists_cross_camera_transition_summary(
        self,
        client,
        admin_headers,
        admin_user,
        db,
    ):
        embedding = [1.0] + ([0.0] * 511)
        visitor = Visitor(
            organization_id=admin_user.organization_id,
            name="Transition Visitor",
            is_known=True,
            is_active=True,
        )
        first_camera = Camera(
            organization_id=admin_user.organization_id,
            name="Front Door Camera",
            rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
            location="Main Entrance",
            is_active=True,
            status="online",
        )
        second_camera = Camera(
            organization_id=admin_user.organization_id,
            name="Back Door Camera",
            rtsp_url="rtsp://test:test@192.168.1.101:554/stream",
            location="Back Exit",
            is_active=True,
            status="online",
        )
        db.add(visitor)
        db.add(first_camera)
        db.add(second_camera)
        db.commit()
        db.refresh(visitor)
        db.refresh(first_camera)
        db.refresh(second_camera)

        db.add(
            FaceData(
                visitor_id=visitor.id,
                embedding=embedding,
                quality_score=0.94,
                face_angle="frontal",
                is_primary=True,
            )
        )
        db.commit()

        for camera_id in (str(first_camera.id), str(second_camera.id)):
            response = client.post(
                f"{BASE}/recognize",
                json={
                    "embedding": embedding,
                    "camera_id": camera_id,
                },
                headers=admin_headers,
            )
            assert response.status_code == 200
            assert response.json()["visitor_id"] == str(visitor.id)

        db.expire_all()
        summary = db.query(CrossCameraMovementSummary).filter(
            CrossCameraMovementSummary.visitor_id == visitor.id,
            CrossCameraMovementSummary.from_camera_id == first_camera.id,
            CrossCameraMovementSummary.to_camera_id == second_camera.id,
        ).first()
        assert summary is not None
        assert int(summary.transition_count or 0) >= 1


class TestHealthAndMetadata:

    def test_recognition_health(self, client):
        response = client.get(f"{BASE}/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_not_found(self, client):
        response = client.get(f"{BASE}/nonexistent")
        assert response.status_code in [404, 405]

    def test_method_not_allowed(self, client):
        response = client.get(f"{BASE}/recognize")
        assert response.status_code == 405


class TestAuthentication:

    def test_protected_endpoints_require_auth(self, client):
        endpoints = [
            ("POST", f"{BASE}/multi-angle/register"),
            ("GET", f"{BASE}/multi-angle/stats"),
            ("POST", f"{BASE}/reid/identify"),
            ("GET", f"{BASE}/reid/track/v1"),
            ("GET", f"{BASE}/emotion/history/v1"),
            ("POST", f"{BASE}/recognize"),
        ]
        for method, url in endpoints:
            if method == "POST":
                resp = client.post(url, json={})
            else:
                resp = client.get(url)
            assert resp.status_code in [401, 403, 422], (
                f"{method} {url} returned {resp.status_code}"
            )


class TestConcurrency:

    def test_concurrent_health_checks(self, client):
        def check():
            return client.get(f"{BASE}/health")

        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: check(), range(10)))

        assert all(r.status_code == 200 for r in results)
