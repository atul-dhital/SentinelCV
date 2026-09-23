import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.paths import data_path
from core.security import hash_password
from models.models import (
    Camera,
    CameraSession,
    DetectionLog,
    FaceData,
    GDPRRequest,
    Organization,
    User,
    Visitor,
    VisitorConsent,
    VisitorLog,
)


def _login_headers(client, email: str, password: str) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _ensure_face_file(relative_path: str) -> Path:
    absolute_path = Path(data_path(relative_path))
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(b"test-face-image")
    return absolute_path


def test_gdpr_export_request_creates_archive(client, admin_headers, admin_user, db):
    visitor = Visitor(
        organization_id=admin_user.organization_id,
        name="GDPR Export Visitor",
        email="gdpr-export@example.com",
        is_known=True,
        is_active=True,
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)

    consent = VisitorConsent(
        visitor_id=visitor.id,
        consent_type="analytics",
        consent_given=True,
    )
    face = FaceData(
        visitor_id=visitor.id,
        embedding=[0.01] * 8,
        image_url="face_images/gdpr-export-face.jpg",
        quality_score=0.95,
        face_angle="frontal",
        is_primary=True,
    )
    db.add(consent)
    db.add(face)
    db.commit()

    response = client.post(
        f"/api/v1/gdpr/export?visitor_id={visitor.id}",
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["response_file_url"]

    archive_path = Path(data_path(payload["response_file_url"]))
    assert archive_path.exists()

    with zipfile.ZipFile(archive_path, "r") as archive:
        names = set(archive.namelist())
        assert "visitor_profile.json" in names
        assert "face_data.json" in names
        assert "consent_records.json" in names


def test_gdpr_request_status_is_org_scoped(client, db, admin_headers, admin_user):
    visitor = Visitor(
        organization_id=admin_user.organization_id,
        name="Scoped GDPR Visitor",
        email="gdpr-scope@example.com",
        is_known=True,
        is_active=True,
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)

    other_org = Organization(name="Other Org")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    other_user = User(
        organization_id=other_org.id,
        email="other-admin@test.com",
        full_name="Other Admin",
        password_hash=hash_password("OtherAdmin123!"),
        role="admin",
    )
    db.add(other_user)
    db.add(
        GDPRRequest(
            visitor_id=visitor.id,
            request_type="data_export",
            status="pending",
            notes="cross-org test",
        )
    )
    db.commit()

    request = db.query(GDPRRequest).filter(GDPRRequest.visitor_id == visitor.id).first()
    other_headers = _login_headers(client, "other-admin@test.com", "OtherAdmin123!")

    response = client.get(
        f"/api/v1/gdpr/requests/{request.id}",
        headers=other_headers,
    )
    assert response.status_code == 404, response.text


def test_gdpr_delete_request_clears_embeddings_and_marks_visitor_inactive(
    client,
    admin_headers,
    admin_user,
    db,
):
    visitor = Visitor(
        organization_id=admin_user.organization_id,
        name="GDPR Delete Visitor",
        email="gdpr-delete@example.com",
        is_known=True,
        is_active=True,
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)

    face = FaceData(
        visitor_id=visitor.id,
        embedding=[0.05] * 16,
        image_url="face_images/gdpr-delete-face.jpg",
        quality_score=0.9,
        face_angle="frontal",
        is_primary=True,
    )
    db.add(face)
    db.commit()

    response = client.post(
        f"/api/v1/gdpr/delete?visitor_id={visitor.id}",
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "processing"

    db.expire_all()
    refreshed_face = db.query(FaceData).filter(FaceData.id == face.id).first()
    refreshed_visitor = db.query(Visitor).filter(Visitor.id == visitor.id).first()

    assert refreshed_face is not None
    assert refreshed_face.embedding is None
    assert refreshed_visitor is not None
    assert refreshed_visitor.is_active is False
    assert refreshed_visitor.is_known is False


def test_gdpr_cleanup_completes_old_deletion_request(
    client,
    admin_headers,
    admin_user,
    db,
):
    visitor = Visitor(
        organization_id=admin_user.organization_id,
        name="GDPR Cleanup Visitor",
        email="gdpr-cleanup@example.com",
        is_known=True,
        is_active=True,
    )
    camera = Camera(
        organization_id=admin_user.organization_id,
        name="GDPR Cleanup Camera",
        rtsp_url="rtsp://cleanup.local/stream",
        is_active=True,
        status="online",
    )
    db.add(visitor)
    db.add(camera)
    db.commit()
    db.refresh(visitor)
    db.refresh(camera)

    image_relative_path = "face_images/gdpr-cleanup-face.jpg"
    image_file = _ensure_face_file(image_relative_path)

    face = FaceData(
        visitor_id=visitor.id,
        embedding=[0.07] * 32,
        image_url=image_relative_path,
        quality_score=0.88,
        face_angle="frontal",
        is_primary=True,
    )
    db.add(face)
    db.commit()
    db.refresh(face)

    session = CameraSession(
        organization_id=admin_user.organization_id,
        user_id=admin_user.id,
        camera_id=camera.id,
        status="ended",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    visitor_log = VisitorLog(
        organization_id=admin_user.organization_id,
        visitor_id=visitor.id,
        camera_id=camera.id,
        face_data_id=face.id,
        face_image_path=image_relative_path,
        video_snippet_path="raw_videos/example.mp4",
        confidence=0.91,
        identified=True,
        status="identified",
    )
    detection_log = DetectionLog(
        session_id=session.id,
        visitor_id=visitor.id,
        confidence=0.93,
        face_image_path=image_relative_path,
        identified=True,
        embedding_snapshot=[0.1] * 8,
    )
    consent = VisitorConsent(
        visitor_id=visitor.id,
        consent_type="face_recognition",
        consent_given=True,
    )
    deletion_request = GDPRRequest(
        visitor_id=visitor.id,
        request_type="data_deletion",
        status="processing",
        request_date=datetime.now(timezone.utc) - timedelta(days=120),
        notes="old deletion request",
    )
    db.add(visitor_log)
    db.add(detection_log)
    db.add(consent)
    db.add(deletion_request)
    db.commit()

    response = client.post(
        f"/api/v1/gdpr/cleanup/{admin_user.organization_id}",
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    stats = payload["stats"]

    assert payload["status"] == "cleanup_completed"
    assert stats["requests_completed"] >= 1
    assert stats["visitors_scrubbed"] >= 1

    db.expire_all()
    refreshed_request = db.query(GDPRRequest).filter(GDPRRequest.id == deletion_request.id).first()
    refreshed_visitor = db.query(Visitor).filter(Visitor.id == visitor.id).first()
    refreshed_log = db.query(VisitorLog).filter(VisitorLog.id == visitor_log.id).first()
    refreshed_detection = db.query(DetectionLog).filter(DetectionLog.id == detection_log.id).first()
    remaining_faces = db.query(FaceData).filter(FaceData.visitor_id == visitor.id).count()
    remaining_consents = db.query(VisitorConsent).filter(VisitorConsent.visitor_id == visitor.id).count()

    assert refreshed_request is not None
    assert refreshed_request.status == "completed"
    assert refreshed_request.completion_date is not None

    assert refreshed_visitor is not None
    assert refreshed_visitor.name is None
    assert refreshed_visitor.email is None
    assert refreshed_visitor.is_active is False
    assert refreshed_visitor.visitor_metadata["gdpr_deleted"] is True

    assert refreshed_log is not None
    assert refreshed_log.visitor_id is None
    assert refreshed_log.face_data_id is None
    assert refreshed_log.face_image_path is None
    assert refreshed_log.video_snippet_path is None
    assert refreshed_log.identified is False
    assert refreshed_log.status == "unidentified"

    assert refreshed_detection is not None
    assert refreshed_detection.visitor_id is None
    assert refreshed_detection.face_image_path is None
    assert refreshed_detection.embedding_snapshot is None
    assert refreshed_detection.identified is False

    assert remaining_faces == 0
    assert remaining_consents == 0
    assert not image_file.exists()
