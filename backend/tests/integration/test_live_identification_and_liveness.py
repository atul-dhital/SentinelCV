"""Regression tests for live identification and liveness verification flows."""

import base64
from types import SimpleNamespace

import cv2
import numpy as np

from models.models import Visitor, VisitorLog
from services.liveness_service import LivenessDetectionService
from services import visitor_service


def _fast_liveness_service(monkeypatch) -> LivenessDetectionService:
    monkeypatch.setattr("services.liveness_service.LivenessDetectionService._load_mediapipe", lambda self: None)
    service = LivenessDetectionService()
    service.face_mesh = None
    service.pose = None
    return service


def _data_url_from_image(fill_value: int = 180) -> str:
    frame = np.full((64, 64, 3), fill_value, dtype=np.uint8)
    frame[8:24, 8:24] = 0
    frame[40:56, 40:56] = 255
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    return f"data:image/jpeg;base64,{base64.b64encode(encoded.tobytes()).decode('ascii')}"


def test_live_camera_identification_flow(client, admin_headers, admin_user, db, monkeypatch):
    sample_visitor = Visitor(
        organization_id=admin_user.organization_id,
        name="Live Camera Visitor",
        email="live-camera@example.com",
        description="Visitor used for live camera identification test",
        is_known=True,
        is_active=True,
    )
    db.add(sample_visitor)
    db.commit()
    db.refresh(sample_visitor)

    embedding = [0.01] * 512
    visitor_face = visitor_service.create_face_data(
        db,
        sample_visitor.id,
        embedding=embedding,
        quality_score=0.99,
        face_angle="frontal",
        is_primary=True,
    )
    frame_data = _data_url_from_image()

    class FakeAiResponse:
        status_code = 200

        def json(self):
            return {
                "faces": [
                    {
                        "bbox": {"x": 1, "y": 2, "w": 8, "h": 8},
                        "embedding": embedding,
                        "face_angle": "frontal",
                        "face_crop_b64": frame_data.split(",", 1)[1],
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            return FakeAiResponse()

    async def fake_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr("api.camera.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("api.camera.realtime_manager.broadcast", fake_broadcast)
    monkeypatch.setattr(
        "api.camera.liveness_detector.ensemble_detection",
        lambda *args, **kwargs: SimpleNamespace(
            is_live=True,
            score=0.97,
            method="ensemble",
            details={"individual_scores": {"texture": 0.96, "deep_learning": 0.98}},
            quality_metrics={"illumination_score": 0.92, "blur_score": 0.08, "noise_level": 0.03},
            attack_detected=False,
            attack_type=None,
        ),
    )

    session_res = client.post(
        "/api/v1/camera/start-session",
        json={"settings": {"source": "pytest_webcam"}},
        headers=admin_headers,
    )
    assert session_res.status_code == 200, session_res.text
    session_id = session_res.json()["id"]

    process_res = client.post(
        "/api/v1/camera/process-frame",
        json={"session_id": session_id, "frame_data": frame_data},
        headers=admin_headers,
    )
    assert process_res.status_code == 200, process_res.text
    payload = process_res.json()
    assert payload["frame_number"] == 1
    assert len(payload["detections"]) == 1
    assert payload["detections"][0]["identified"] is True
    assert payload["detections"][0]["visitor_id"] == str(sample_visitor.id)
    assert payload["detections"][0]["visitor_name"] == sample_visitor.name

    logs_res = client.get(f"/api/v1/camera/session/{session_id}/logs", headers=admin_headers)
    assert logs_res.status_code == 200, logs_res.text

    end_res = client.post(f"/api/v1/camera/end-session/{session_id}", headers=admin_headers)
    assert end_res.status_code == 200, end_res.text

    assert str(visitor_face.id) != ""


def test_live_camera_identification_keeps_match_without_attack_signal(client, admin_headers, admin_user, db, monkeypatch):
    sample_visitor = Visitor(
        organization_id=admin_user.organization_id,
        name="Live Camera Visitor",
        email="live-camera-soft-liveness@example.com",
        description="Visitor used for low-confidence single-frame liveness regression",
        is_known=True,
        is_active=True,
    )
    db.add(sample_visitor)
    db.commit()
    db.refresh(sample_visitor)

    embedding = [0.02] * 512
    visitor_face = visitor_service.create_face_data(
        db,
        sample_visitor.id,
        embedding=embedding,
        quality_score=0.99,
        face_angle="frontal",
        is_primary=True,
    )
    frame_data = _data_url_from_image(190)

    class FakeAiResponse:
        status_code = 200

        def json(self):
            return {
                "faces": [
                    {
                        "bbox": {"x": 1, "y": 2, "w": 8, "h": 8},
                        "embedding": embedding,
                        "face_angle": "frontal",
                        "face_crop_b64": frame_data.split(",", 1)[1],
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            return FakeAiResponse()

    async def fake_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr("api.camera.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("api.camera.realtime_manager.broadcast", fake_broadcast)
    monkeypatch.setattr(
        "api.camera.visitor_service.search_visitor_by_embedding",
        lambda *args, **kwargs: (
            sample_visitor,
            0.97,
            visitor_face.id,
            {"frontal": 0.97},
        ),
    )
    monkeypatch.setattr(
        "api.camera.liveness_detector.ensemble_detection",
        lambda *args, **kwargs: SimpleNamespace(
            is_live=False,
            score=0.42,
            method="ensemble",
            details={"individual_scores": {"texture": 0.81, "deep_learning": 0.03}},
            quality_metrics={"illumination_score": 0.75, "blur_score": 0.18, "noise_level": 0.02},
            attack_detected=False,
            attack_type=None,
        ),
    )

    session_res = client.post(
        "/api/v1/camera/start-session",
        json={"settings": {"source": "pytest_webcam"}},
        headers=admin_headers,
    )
    assert session_res.status_code == 200, session_res.text
    session_id = session_res.json()["id"]

    process_res = client.post(
        "/api/v1/camera/process-frame",
        json={"session_id": session_id, "frame_data": frame_data},
        headers=admin_headers,
    )
    assert process_res.status_code == 200, process_res.text
    detection = process_res.json()["detections"][0]
    assert detection["identified"] is True
    assert detection["visitor_id"] == str(sample_visitor.id)

    end_res = client.post(f"/api/v1/camera/end-session/{session_id}", headers=admin_headers)
    assert end_res.status_code == 200, end_res.text


def test_liveness_challenge_start_and_verify_flow(client, admin_headers, admin_user, db, monkeypatch):
    sample_visitor = Visitor(
        organization_id=admin_user.organization_id,
        name="Liveness Visitor",
        email="liveness@example.com",
        description="Visitor used for liveness verification test",
        is_known=True,
        is_active=True,
    )
    db.add(sample_visitor)
    db.commit()
    db.refresh(sample_visitor)

    visitor_log = VisitorLog(
        organization_id=admin_user.organization_id,
        visitor_id=sample_visitor.id,
        confidence=0.93,
        identified=True,
        status="identified",
        source_video="pytest",
    )
    db.add(visitor_log)
    db.commit()
    db.refresh(visitor_log)

    monkeypatch.setattr(
        "api.liveness._ensure_org_config",
        lambda db, organization_id: SimpleNamespace(
            verify_challenge=lambda challenge_type, frames, fps=30: (
                True,
                0.94,
                {"challenge_type": challenge_type, "frame_count": len(frames)},
            ),
            ensemble_detection=lambda frame=None, frames=None, methods=None: SimpleNamespace(
                is_live=True,
                score=0.94,
                details={"individual_scores": {"texture": 0.9, "deep_learning": 0.98}},
            )
        ),
    )
    monkeypatch.setattr(
        "api.liveness._prepare_challenge_frames",
        lambda frames, max_frames=18: (frames, {"sampled_frame_count": len(frames), "face_crops_applied": len(frames)}),
    )

    start_res = client.post(
        "/api/v1/liveness/challenge/start",
        json={"visitor_log_id": str(visitor_log.id), "challenge_type": "blink"},
        headers=admin_headers,
    )
    assert start_res.status_code == 200, start_res.text
    challenge_id = start_res.json()["challenge_id"]

    verify_res = client.post(
        "/api/v1/liveness/challenge/verify",
        json={
            "challenge_id": challenge_id,
            "video_frames": [_data_url_from_image(200), _data_url_from_image(210)],
        },
        headers=admin_headers,
    )
    assert verify_res.status_code == 200, verify_res.text
    verification = verify_res.json()
    assert verification["challenge_id"] == challenge_id
    assert verification["verified"] is True
    assert verification["confidence"] == 0.94
    assert verification["details"]["frame_count"] == 2
    assert verification["details"]["face_crops_applied"] == 2


def test_single_frame_liveness_does_not_flag_replay_without_motion(monkeypatch):
    service = _fast_liveness_service(monkeypatch)
    frame = np.full((32, 32, 3), 180, dtype=np.uint8)

    monkeypatch.setattr(
        service,
        "detect_liveness_texture_based",
        lambda frame: (0.82, {"entropy_normalized": 0.82}),
    )
    monkeypatch.setattr(
        service,
        "detect_liveness_deep_learning",
        lambda frame: (
            0.74,
            {"quality_metrics": {"blur_score": 0.2, "illumination_score": 0.8}},
        ),
    )

    result = service.ensemble_detection(frame=frame, methods=["texture", "deep_learning"])

    assert result.is_live is True
    assert result.attack_detected is False
    assert result.attack_type is None


def test_fallback_blink_challenge_detects_eye_state_transition(monkeypatch):
    service = _fast_liveness_service(monkeypatch)
    frames = [np.full((24, 24, 3), 170, dtype=np.uint8) for _ in range(6)]

    monkeypatch.setattr(service, "_detect_eye_counts", lambda gray_frames: [2, 2, 0, 0, 2, 2])

    passed, confidence, details = service.verify_challenge("blink", frames)

    assert passed is True
    assert confidence == 1.0
    assert details["method"] == "haar_eye_state"
    assert details["blinks_detected"] == 1


def test_eye_count_detection_uses_secondary_cascade_when_primary_misses(monkeypatch):
    service = _fast_liveness_service(monkeypatch)
    gray_frame = np.full((96, 96), 160, dtype=np.uint8)

    class StaticCascade:
        def __init__(self, detections):
            self._detections = detections

        def empty(self):
            return False

        def detectMultiScale(self, *args, **kwargs):
            return self._detections

    monkeypatch.setattr(service, "_detect_primary_face", lambda frame: (16, 16, 64, 64))
    service.eye_cascade = StaticCascade([])
    service.eye_cascade_alt = StaticCascade([(8, 8, 12, 8)])

    assert service._detect_eye_counts([gray_frame]) == [1]


def test_fallback_smile_challenge_uses_smile_scores(monkeypatch):
    service = _fast_liveness_service(monkeypatch)
    frames = [np.full((24, 24, 3), 160 + i, dtype=np.uint8) for i in range(5)]

    monkeypatch.setattr(
        service,
        "_detect_smile_scores",
        lambda gray_frames: [0.0, 0.0, 0.024, 0.026, 0.021],
    )

    passed, confidence, details = service.verify_challenge("smile", frames)

    assert passed is True
    assert confidence > 0.0
    assert details["method"] == "brightness_analysis + haar_smile"
    assert details["smile_frame_ratio"] >= 0.2


def test_smile_challenge_requires_stronger_brightness_without_smile_evidence(monkeypatch):
    service = _fast_liveness_service(monkeypatch)
    frames = [np.full((24, 24, 3), 160 + i, dtype=np.uint8) for i in range(5)]

    monkeypatch.setattr(service, "_detect_smile_scores", lambda gray_frames: [0.0] * len(gray_frames))

    passed, confidence, details = service.verify_challenge("smile", frames)

    assert passed is False
    assert confidence < 0.3
    assert details["method"] == "brightness_analysis"
    assert details["brightness_threshold"] == 6.0


def test_fallback_head_turn_uses_face_track_when_flow_is_small(monkeypatch):
    service = _fast_liveness_service(monkeypatch)
    frames = [np.full((24, 24, 3), 150, dtype=np.uint8) for _ in range(4)]

    monkeypatch.setattr(
        service,
        "_track_face_motion",
        lambda gray_frames: [(20.0, 12.0, 40.0), (26.0, 12.0, 40.0), (32.0, 12.0, 40.0)],
    )
    monkeypatch.setattr(
        "services.liveness_service.cv2.calcOpticalFlowFarneback",
        lambda *args, **kwargs: np.zeros((24, 24, 2), dtype=np.float32),
    )
    monkeypatch.setattr(
        "services.liveness_service.cv2.cartToPolar",
        lambda x, y: (np.zeros((24, 24), dtype=np.float32), np.zeros((24, 24), dtype=np.float32)),
    )

    passed, confidence, details = service.verify_challenge("head_turn", frames)

    assert passed is True
    assert confidence > 0.0
    assert details["method"] == "optical_flow + face_track"
    assert details["face_track_samples"] == 3


def test_head_turn_optical_flow_passes_for_realistic_webcam_motion(monkeypatch):
    service = _fast_liveness_service(monkeypatch)
    frames = [np.full((24, 24, 3), 150, dtype=np.uint8) for _ in range(4)]
    magnitudes = iter([0.22, 0.31, 0.61])

    monkeypatch.setattr(service, "_track_face_motion", lambda gray_frames: [])
    monkeypatch.setattr(
        "services.liveness_service.cv2.calcOpticalFlowFarneback",
        lambda *args, **kwargs: np.zeros((24, 24, 2), dtype=np.float32),
    )
    monkeypatch.setattr(
        "services.liveness_service.cv2.cartToPolar",
        lambda x, y: (
            np.full((24, 24), next(magnitudes), dtype=np.float32),
            np.zeros((24, 24), dtype=np.float32),
        ),
    )

    passed, confidence, details = service.verify_challenge("head_turn", frames)

    assert passed is True
    assert confidence > 0.0
    assert details["method"] == "optical_flow"
    assert details["max_optical_flow"] >= details["threshold"]
    assert details["avg_optical_flow"] >= details["avg_flow_threshold"]


def test_head_turn_optical_flow_rejects_low_motion(monkeypatch):
    service = _fast_liveness_service(monkeypatch)
    frames = [np.full((24, 24, 3), 150, dtype=np.uint8) for _ in range(4)]
    magnitudes = iter([0.08, 0.11, 0.10])

    monkeypatch.setattr(service, "_track_face_motion", lambda gray_frames: [])
    monkeypatch.setattr(
        "services.liveness_service.cv2.calcOpticalFlowFarneback",
        lambda *args, **kwargs: np.zeros((24, 24, 2), dtype=np.float32),
    )
    monkeypatch.setattr(
        "services.liveness_service.cv2.cartToPolar",
        lambda x, y: (
            np.full((24, 24), next(magnitudes), dtype=np.float32),
            np.zeros((24, 24), dtype=np.float32),
        ),
    )

    passed, confidence, details = service.verify_challenge("head_turn", frames)

    assert passed is False
    assert confidence < 0.5
    assert details["method"] == "optical_flow"
    assert details["avg_optical_flow"] < details["avg_flow_threshold"]


def test_head_turn_normalizes_mixed_frame_sizes(monkeypatch):
    service = _fast_liveness_service(monkeypatch)
    frames = [
        np.full((40, 50, 3), 120, dtype=np.uint8),
        np.full((32, 44, 3), 130, dtype=np.uint8),
        np.full((36, 48, 3), 140, dtype=np.uint8),
    ]

    def _fake_flow(prev, next_frame, *args, **kwargs):
        assert prev.shape == next_frame.shape
        return np.zeros((prev.shape[0], prev.shape[1], 2), dtype=np.float32)

    monkeypatch.setattr(service, "_track_face_motion", lambda gray_frames: [])
    monkeypatch.setattr(
        "services.liveness_service.cv2.calcOpticalFlowFarneback",
        _fake_flow,
    )
    monkeypatch.setattr(
        "services.liveness_service.cv2.cartToPolar",
        lambda x, y: (
            np.full((x.shape[0], x.shape[1]), 0.12, dtype=np.float32),
            np.zeros((x.shape[0], x.shape[1]), dtype=np.float32),
        ),
    )

    passed, confidence, details = service.verify_challenge("head_turn", frames)

    assert passed is False
    assert confidence >= 0.0
    assert details["method"] == "optical_flow"


def test_prepare_challenge_frames_samples_and_applies_face_crops(monkeypatch):
    from api import liveness as liveness_api

    frames = [np.full((12, 12, 3), 100 + idx, dtype=np.uint8) for idx in range(6)]

    monkeypatch.setattr(
        liveness_api,
        "_extract_face_frame",
        lambda frame: np.full((8, 8, 3), 220, dtype=np.uint8),
    )

    prepared_frames, details = liveness_api._prepare_challenge_frames(frames, max_frames=3)

    assert len(prepared_frames) == 3
    assert all(frame.shape == (8, 8, 3) for frame in prepared_frames)
    assert details["sampled_frame_count"] == 3
    assert details["face_crops_applied"] == 3


def test_liveness_report_serializes_organization_id(client, admin_headers, admin_user, monkeypatch):
    from schemas.schemas import LivenessStatistics

    monkeypatch.setattr(
        "api.liveness._svc_get_liveness_statistics",
        lambda db, organization_id: LivenessStatistics(
            total_detections=0,
            live_count=0,
            spoof_count=0,
            live_percentage=0.0,
            average_liveness_score=0.0,
            most_common_rejection_reason=None,
            attack_detection_rate=0.0,
            average_processing_time_ms=0.0,
            method_distribution={},
        ),
    )

    response = client.get("/api/v1/liveness/report", headers=admin_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["organization_id"] == str(admin_user.organization_id)
