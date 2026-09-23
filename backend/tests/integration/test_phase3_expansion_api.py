import pytest
from datetime import datetime, timedelta, timezone

from api.advanced_recognition import reset_runtime_state
from models.models import (
    BehaviorEvent,
    Camera,
    FaceData,
    VisionAnalyticsEvent,
    Visitor,
    VisitorLog,
)


API = "/api/v1"


@pytest.fixture(autouse=True)
def reset_phase3_runtime():
    reset_runtime_state()
    yield
    reset_runtime_state()


def _create_org_scoped_visitor(db, admin_user, name: str) -> Visitor:
    visitor = Visitor(
        organization_id=admin_user.organization_id,
        name=name,
        is_known=True,
        is_active=True,
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)
    return visitor


def test_emotion_detection_persists_behavior_event_and_history(
    client,
    admin_headers,
    admin_user,
    db,
):
    visitor = Visitor(
        organization_id=admin_user.organization_id,
        name="Emotion Visitor",
        is_known=True,
        is_active=True,
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)

    response = client.post(
        f"{API}/recognition/advanced/emotion/detect",
        params={"visitor_id": str(visitor.id)},
        json=[0.92] * 128,
        headers=admin_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["emotion"] in {"happy", "neutral", "sad", "angry", "surprised", "fear", "disgust"}
    assert payload["intensity"] > 0.0

    history = client.get(
        f"{API}/recognition/advanced/emotion/history/{visitor.id}",
        headers=admin_headers,
    )
    assert history.status_code == 200
    history_payload = history.json()
    assert history_payload["event_count"] >= 1
    assert history_payload["average_valence"] is not None
    assert history_payload["average_arousal"] is not None

    db.expire_all()
    event = db.query(BehaviorEvent).filter(
        BehaviorEvent.visitor_id == visitor.id,
        BehaviorEvent.source == "advanced_recognition_emotion_api",
    ).first()
    assert event is not None
    assert event.details["dominant_emotion"] == payload["emotion"]


def test_multimodal_auto_embedding_builds_profile(
    client,
    admin_headers,
    admin_user,
    db,
):
    visitor = _create_org_scoped_visitor(db, admin_user, "Multimodal Visitor")
    db.add(
        FaceData(
            visitor_id=visitor.id,
            embedding=[0.14] * 128,
            quality_score=0.91,
            face_angle="frontal",
            is_primary=True,
        )
    )
    db.commit()

    audio = client.post(
        f"{API}/multimodal/audio-features",
        headers=admin_headers,
        json={
            "visitor_id": str(visitor.id),
            "mfcc_features": [0.2] * 32,
            "voice_confidence": 0.78,
            "pitch_frequency": 220.0,
            "audio_duration_ms": 2100,
        },
    )
    assert audio.status_code == 201

    text = client.post(
        f"{API}/multimodal/text-bio",
        headers=admin_headers,
        json={
            "visitor_id": str(visitor.id),
            "name": visitor.name,
            "department": "Research",
            "position": "Engineer",
            "notes": "Prefers guided entry support.",
            "embedding_confidence": 0.71,
        },
    )
    assert text.status_code == 201

    embedding = client.post(
        f"{API}/multimodal/embeddings/auto",
        headers=admin_headers,
        json={
            "visitor_id": str(visitor.id),
            "sensor_data": {"microphone": True, "badge_reader": True},
        },
    )
    assert embedding.status_code == 201
    embedding_payload = embedding.json()
    assert embedding_payload["audio_present"] is True
    assert embedding_payload["text_present"] is True
    assert embedding_payload["fusion_score"] > 0.0

    profile = client.get(
        f"{API}/multimodal/visitors/{visitor.id}/profile",
        headers=admin_headers,
    )
    assert profile.status_code == 200
    profile_payload = profile.json()
    assert profile_payload["modalities_present"]["face"] is True
    assert profile_payload["modalities_present"]["audio"] is True
    assert profile_payload["modalities_present"]["text"] is True
    assert profile_payload["modality_counts"]["multimodal"] >= 1


def test_multimodal_infer_ranks_matching_face_candidate(
    client,
    admin_headers,
    admin_user,
    db,
):
    visitor = _create_org_scoped_visitor(db, admin_user, "Multimodal Infer Visitor")
    db.add(
        FaceData(
            visitor_id=visitor.id,
            embedding=[0.31] * 512,
            quality_score=0.93,
            face_angle="frontal",
            is_primary=True,
        )
    )
    db.commit()

    response = client.post(
        f"{API}/multimodal/infer",
        headers=admin_headers,
        json={
            "face_embedding": [0.31] * 512,
            "top_k": 3,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert "face" in payload["query_modalities"]
    assert payload["match_found"] is True
    assert len(payload["candidates"]) >= 1

    top_candidate = payload["candidates"][0]
    assert top_candidate["visitor_id"] == str(visitor.id)
    assert top_candidate["meets_threshold"] is True
    assert top_candidate["modalities"].get("face", 0.0) >= 0.99
    assert top_candidate["score"] >= payload["threshold"]


def test_future_enhancements_cross_camera_search_returns_pose_fields(
    client,
    admin_headers,
    admin_user,
    db,
):
    visitor = _create_org_scoped_visitor(db, admin_user, "Pose ReID Visitor")

    camera_a = Camera(
        organization_id=admin_user.organization_id,
        name="Pose Cam A",
        location="Entrance",
        is_active=True,
        status="online",
    )
    camera_b = Camera(
        organization_id=admin_user.organization_id,
        name="Pose Cam B",
        location="Lobby",
        is_active=True,
        status="online",
    )
    db.add_all([camera_a, camera_b])
    db.flush()

    face_a = FaceData(
        visitor_id=visitor.id,
        embedding=[0.11] * 128,
        quality_score=0.88,
        face_angle="frontal",
        is_primary=True,
    )
    face_b = FaceData(
        visitor_id=visitor.id,
        embedding=[0.12] * 128,
        quality_score=0.9,
        face_angle="profile",
        is_primary=False,
    )
    db.add_all([face_a, face_b])
    db.flush()

    now = datetime.now(timezone.utc)
    first_seen = now - timedelta(minutes=6)
    second_seen = now - timedelta(minutes=3)

    db.add_all(
        [
            VisitorLog(
                organization_id=admin_user.organization_id,
                visitor_id=visitor.id,
                camera_id=camera_a.id,
                face_data_id=face_a.id,
                timestamp=first_seen,
                confidence=0.86,
                identified=True,
                status="identified",
            ),
            VisitorLog(
                organization_id=admin_user.organization_id,
                visitor_id=visitor.id,
                camera_id=camera_b.id,
                face_data_id=face_b.id,
                timestamp=second_seen,
                confidence=0.9,
                identified=True,
                status="identified",
            ),
            VisionAnalyticsEvent(
                organization_id=admin_user.organization_id,
                camera_id=camera_a.id,
                event_type="pose_estimate",
                source="integration_test",
                status="ok",
                confidence=0.87,
                posture="standing",
                payload={"average_visibility": 0.84, "keypoint_count": 15},
                created_at=first_seen,
            ),
            VisionAnalyticsEvent(
                organization_id=admin_user.organization_id,
                camera_id=camera_b.id,
                event_type="pose_estimate",
                source="integration_test",
                status="ok",
                confidence=0.91,
                posture="walking",
                payload={"average_visibility": 0.88, "keypoint_count": 16},
                created_at=second_seen,
            ),
        ]
    )
    db.commit()

    response = client.post(
        f"{API}/future-enhancements/reid/cross-camera/search",
        headers=admin_headers,
        json={
            "lookback_minutes": 120,
            "min_camera_count": 2,
            "min_sightings": 2,
            "limit": 5,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["matches"]

    match = payload["matches"][0]
    assert match["visitor_id"] == str(visitor.id)
    assert match["pose_quality_score"] > 0.0
    assert match["pose_samples"] >= 1
    assert isinstance(match["angle_distribution"], dict)
    assert "frontal" in match["angle_distribution"]
    assert isinstance(match["posture_distribution"], dict)
    assert any(key in match["posture_distribution"] for key in ["standing", "walking"])


def test_three_d_face_capture_auto_embedding_and_identify(
    client,
    admin_headers,
    admin_user,
    db,
):
    visitor = _create_org_scoped_visitor(db, admin_user, "3D Visitor")
    capture_payload = {
        "visitor_id": str(visitor.id),
        "depth_map_path": "captures/shared_depth.png",
        "point_cloud_path": "captures/shared_cloud.pcd",
        "texture_map_path": "captures/shared_texture.png",
        "face_mesh": {"nose": [0.1, 0.3, 0.2], "eyes": [[0.2, 0.1], [0.8, 0.1]]},
        "face_width_mm": 143.2,
        "face_height_mm": 188.4,
        "face_depth_mm": 122.7,
        "forehead_width_mm": 112.1,
        "nose_height_mm": 54.3,
        "capture_quality_score": 0.82,
        "mesh_density": 8200,
        "depth_map_resolution": "640x480",
    }

    first = client.post(
        f"{API}/3d-face/capture",
        headers=admin_headers,
        json=capture_payload,
    )
    second = client.post(
        f"{API}/3d-face/capture",
        headers=admin_headers,
        json=capture_payload,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["embedding_confidence"] > 0.0

    identify = client.get(
        f"{API}/3d-face/identify/{first.json()['id']}",
        headers=admin_headers,
        params={"limit": 3, "match_threshold": 0.7},
    )
    assert identify.status_code == 200
    matches = identify.json()["matches"]
    assert matches
    assert matches[0]["visitor_id"] == str(visitor.id)
    assert matches[0]["match_confidence"] >= 0.7


def test_federated_round_flow_is_org_scoped_and_upserts_participants(
    client,
    admin_headers,
):
    init = client.post(
        f"{API}/federated/rounds",
        headers=admin_headers,
        json={
            "model_type": "face_recognition",
            "num_participants": 4,
            "config": {
                "min_participants": 2,
                "aggregation_strategy": "fedavg",
                "differential_privacy": {"enabled": False},
            },
        },
    )
    assert init.status_code == 200
    round_id = init.json()["round_id"]

    submit_a = client.post(
        f"{API}/federated/rounds/{round_id}/submit",
        headers=admin_headers,
        json={
            "round_id": round_id,
            "participant_id": "edge-node-1",
            "weight_deltas": [0.1, 0.2, 0.3],
            "local_accuracy": 0.91,
            "local_loss": 0.12,
            "num_samples": 40,
        },
    )
    assert submit_a.status_code == 200

    submit_a_repeat = client.post(
        f"{API}/federated/rounds/{round_id}/submit",
        headers=admin_headers,
        json={
            "round_id": round_id,
            "participant_id": "edge-node-1",
            "weight_deltas": [0.15, 0.25, 0.35],
            "local_accuracy": 0.93,
            "local_loss": 0.09,
            "num_samples": 45,
        },
    )
    assert submit_a_repeat.status_code == 200

    status_after_repeat = client.get(
        f"{API}/federated/rounds/{round_id}",
        headers=admin_headers,
    )
    assert status_after_repeat.status_code == 200
    status_payload = status_after_repeat.json()
    assert status_payload["num_participants_submitted"] == 1
    assert status_payload["participants"][0]["local_accuracy"] == 0.93

    submit_b = client.post(
        f"{API}/federated/rounds/{round_id}/submit",
        headers=admin_headers,
        json={
            "round_id": round_id,
            "participant_id": "edge-node-2",
            "weight_deltas": [0.05, 0.15, 0.2],
            "local_accuracy": 0.88,
            "local_loss": 0.14,
            "num_samples": 30,
        },
    )
    assert submit_b.status_code == 200

    aggregate = client.post(
        f"{API}/federated/rounds/{round_id}/aggregate",
        headers=admin_headers,
    )
    assert aggregate.status_code == 200
    aggregate_payload = aggregate.json()
    assert aggregate_payload["status"] == "aggregated"
    assert aggregate_payload["num_participants"] == 2
    assert aggregate_payload["global_accuracy"] > 0.0


def test_edge_device_deploy_sync_and_summary(
    client,
    admin_headers,
    admin_user,
    db,
):
    visitor = _create_org_scoped_visitor(db, admin_user, "Edge Sync Visitor")
    register_model = client.post(
        f"{API}/model-versions",
        headers=admin_headers,
        json={
            "name": "Edge Face Model",
            "version": "3.2.1",
            "model_type": "face_recognition",
            "file_path": "artifacts/edge-face-v3.2.1.onnx",
            "metrics": {"accuracy": 0.962, "precision": 0.95},
        },
    )
    assert register_model.status_code == 200
    model_id = register_model.json()["id"]

    create_device = client.post(
        f"{API}/edge-devices/",
        headers=admin_headers,
        json={
            "name": "Jetson Lobby 01",
            "device_type": "jetson",
            "location": "Lobby",
            "endpoint_url": "http://10.0.0.55:8080",
            "device_config": {"quantized": True, "target_runtime": "tensorrt"},
        },
    )
    assert create_device.status_code == 200
    device_payload = create_device.json()
    device_id = device_payload["device"]["id"]
    edge_token = device_payload["device_token"]
    assert device_payload["device"]["device_config"]["quantized"] is True

    deploy = client.post(
        f"{API}/edge-devices/{device_id}/deploy-model",
        headers=admin_headers,
        json={
            "model_version_id": model_id,
            "deployment_config": {"channel": "stable", "warmup_frames": 8},
        },
    )
    assert deploy.status_code == 200
    deploy_payload = deploy.json()
    assert deploy_payload["deployed_model_version_id"] == model_id
    assert deploy_payload["device"]["model_version_id"] == model_id

    heartbeat = client.post(
        f"{API}/edge-devices/heartbeat",
        headers={"X-Edge-Token": edge_token},
        json={
            "status": "online",
            "metrics": {"fps": 22.4, "latency_ms": 12.6},
            "model_version_id": model_id,
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == "online"

    db.add(
        FaceData(
            visitor_id=visitor.id,
            embedding=[0.33] * 128,
            quality_score=0.89,
            face_angle="frontal",
            is_primary=True,
        )
    )
    db.commit()

    sync = client.post(
        f"{API}/edge-devices/sync/embeddings",
        headers={"X-Edge-Token": edge_token},
        json={"offset": 0, "limit": 50},
    )
    assert sync.status_code == 200
    sync_payload = sync.json()
    assert sync_payload["count"] >= 1

    events = client.get(
        f"{API}/edge-devices/{device_id}/events",
        headers=admin_headers,
    )
    assert events.status_code == 200
    assert any(event["event_type"] == "deployment" for event in events.json())

    summary = client.get(
        f"{API}/edge-devices/dashboard/summary",
        headers=admin_headers,
    )
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["total_devices"] >= 1
    assert summary_payload["deployed_devices"] >= 1
    assert summary_payload["online_devices"] >= 1
