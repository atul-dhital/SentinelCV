from datetime import datetime, timedelta

from models.models import Camera


class _FakeSnapshotResponse:
    status_code = 200
    content = b"fake-jpeg-data"
    headers = {"content-type": "image/jpeg"}

    def json(self):
        return {}


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json):
        return _FakeSnapshotResponse()


def _create_camera(db, admin_user, *, status="offline") -> Camera:
    camera = Camera(
        organization_id=admin_user.organization_id,
        name="Realtime Test Camera",
        rtsp_url="rtsp://example.local/test-stream",
        location="Lab",
        is_active=True,
        status=status,
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


def test_stream_frame_refreshes_last_seen_for_online_camera(
    client, admin_headers, admin_user, db, monkeypatch
):
    sample_camera = _create_camera(db, admin_user, status="online")
    previous_seen = datetime(2000, 1, 1, 0, 0, 0)
    sample_camera.last_seen = previous_seen
    db.commit()

    async def fake_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr("api.cameras.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr("api.cameras.realtime_manager.broadcast", fake_broadcast)

    response = client.get(
        f"/api/v1/cameras/{sample_camera.id}/stream-frame",
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/jpeg")

    db.refresh(sample_camera)
    assert sample_camera.status == "online"
    assert sample_camera.last_seen is not None
    assert sample_camera.last_seen > previous_seen


def test_stream_frame_broadcasts_status_change_when_camera_recovers(
    client, admin_headers, admin_user, db, monkeypatch
):
    sample_camera = _create_camera(db, admin_user, status="offline")
    sample_camera.status = "offline"
    sample_camera.last_seen = None
    db.commit()

    broadcasts: list[tuple[str, str, dict]] = []

    async def fake_broadcast(organization_id, event_type, payload):
        broadcasts.append((organization_id, event_type, payload))

    monkeypatch.setattr("api.cameras.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr("api.cameras.realtime_manager.broadcast", fake_broadcast)

    response = client.get(
        f"/api/v1/cameras/{sample_camera.id}/stream-frame",
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text

    assert len(broadcasts) == 1
    organization_id, event_type, payload = broadcasts[0]
    assert organization_id == str(sample_camera.organization_id)
    assert event_type == "camera.status_changed"
    assert payload["id"] == str(sample_camera.id)
    assert payload["status"] == "online"
    assert payload["last_seen"] is not None


def test_ending_one_session_does_not_mark_camera_offline_while_another_is_active(
    client, admin_headers, admin_user, db, monkeypatch
):
    sample_camera = _create_camera(db, admin_user, status="offline")
    broadcasts: list[tuple[str, str, dict]] = []

    async def fake_broadcast(organization_id, event_type, payload):
        broadcasts.append((organization_id, event_type, payload))

    monkeypatch.setattr("api.camera.realtime_manager.broadcast", fake_broadcast)

    first_session = client.post(
        "/api/v1/camera/start-session",
        json={"camera_id": str(sample_camera.id), "settings": {"source": "pytest-a"}},
        headers=admin_headers,
    )
    assert first_session.status_code == 200, first_session.text

    second_session = client.post(
        "/api/v1/camera/start-session",
        json={"camera_id": str(sample_camera.id), "settings": {"source": "pytest-b"}},
        headers=admin_headers,
    )
    assert second_session.status_code == 200, second_session.text

    end_first = client.post(
        f"/api/v1/camera/end-session/{first_session.json()['id']}",
        headers=admin_headers,
    )
    assert end_first.status_code == 200, end_first.text

    db.refresh(sample_camera)
    assert sample_camera.status == "online"

    end_second = client.post(
        f"/api/v1/camera/end-session/{second_session.json()['id']}",
        headers=admin_headers,
    )
    assert end_second.status_code == 200, end_second.text

    db.refresh(sample_camera)
    assert sample_camera.status == "offline"
    assert any(event_type == "camera.status_changed" and payload["status"] == "offline" for _, event_type, payload in broadcasts)
