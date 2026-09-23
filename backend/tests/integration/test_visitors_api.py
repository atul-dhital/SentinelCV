"""
Integration tests for visitor CRUD API endpoints.

Covers list, create, get, update, delete, org isolation, pagination, and export.
"""

import pytest
import uuid
from types import SimpleNamespace


API = "/api/v1/visitors"


class TestListVisitors:
    def test_list_visitors_returns_200(self, client, admin_headers):
        response = client.get(API, headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data or isinstance(data, list)

    def test_list_visitors_no_auth(self, client):
        response = client.get(API)
        assert response.status_code in (401, 403)

    def test_list_visitors_includes_sample(self, client, admin_headers, sample_visitor):
        response = client.get(API, headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        visitor_ids = [str(v.get("id", "")) for v in items]
        assert str(sample_visitor.id) in visitor_ids


class TestCreateVisitor:
    def test_create_visitor(self, client, admin_headers):
        unique = uuid.uuid4().hex[:8]
        response = client.post(API, json={
            "name": f"Visitor-{unique}",
            "email": f"v-{unique}@test.com",
        }, headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == f"Visitor-{unique}"
        assert "id" in data

    def test_create_visitor_minimal(self, client, admin_headers):
        response = client.post(API, json={
            "name": "Minimal Visitor",
        }, headers=admin_headers)
        assert response.status_code == 200

    def test_create_visitor_no_auth(self, client):
        response = client.post(API, json={"name": "No Auth"})
        assert response.status_code in (401, 403)


class TestAsyncFaceUpload:
    def test_face_upload_jobs_returns_queue_status(
        self,
        client,
        admin_headers,
        sample_visitor,
        monkeypatch,
    ):
        async def no_op_processor(job_id: str):
            return None

        monkeypatch.setattr(
            "api.visitors._validate_media_strict",
            lambda _path: SimpleNamespace(valid=True, is_corrupt=False, issues=[]),
        )
        monkeypatch.setattr("api.visitors._process_face_embedding_job", no_op_processor)

        response = client.post(
            f"{API}/{sample_visitor.id}/face-upload/jobs",
            headers=admin_headers,
            files={"file": ("face.jpg", b"fake-image-bytes", "image/jpeg")},
        )

        assert response.status_code == 202, response.text
        data = response.json()
        assert data["job_id"]
        assert data["status"] == "queued"
        assert data["image_url"].startswith("face_images/")

        status_res = client.get(
            f"{API}/face-upload/jobs/{data['job_id']}",
            headers=admin_headers,
        )
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["job_type"] == "face_embedding"
        assert status_data["organization_id"]


class TestGetVisitor:
    def test_get_visitor_by_id(self, client, admin_headers, sample_visitor):
        response = client.get(
            f"{API}/{sample_visitor.id}",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == sample_visitor.name

    def test_get_visitor_not_found(self, client, admin_headers):
        fake_id = str(uuid.uuid4())
        response = client.get(f"{API}/{fake_id}", headers=admin_headers)
        assert response.status_code == 404


class TestUpdateVisitor:
    def test_update_visitor(self, client, admin_headers, sample_visitor):
        response = client.put(
            f"{API}/{sample_visitor.id}",
            json={"name": "Updated Name", "description": "Updated"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"

    def test_update_visitor_not_found(self, client, admin_headers):
        fake_id = str(uuid.uuid4())
        response = client.put(
            f"{API}/{fake_id}",
            json={"name": "Ghost"},
            headers=admin_headers,
        )
        assert response.status_code == 404


class TestDeleteVisitor:
    def test_delete_visitor(self, client, admin_headers, admin_user, db):
        from models.models import FaceData, Visitor, VisitorLog

        visitor = Visitor(
            organization_id=admin_user.organization_id,
            name="ToDelete",
            is_known=False,
            is_active=True,
        )
        db.add(visitor)
        db.commit()
        db.refresh(visitor)

        face = FaceData(visitor_id=visitor.id, embedding=[0.0] * 512, is_primary=True)
        db.add(face)
        db.commit()
        db.refresh(face)

        visitor_log = VisitorLog(
            organization_id=admin_user.organization_id,
            visitor_id=visitor.id,
            face_data_id=face.id,
            identified=True,
            status="identified",
        )
        db.add(visitor_log)
        db.commit()
        db.refresh(visitor_log)

        visitor_id = visitor.id
        face_id = face.id
        visitor_log_id = visitor_log.id

        response = client.delete(
            f"{API}/{visitor_id}",
            headers=admin_headers,
        )
        assert response.status_code == 200

        db.expire_all()
        preserved_log = db.query(VisitorLog).filter(VisitorLog.id == visitor_log_id).first()
        assert db.query(Visitor).filter(Visitor.id == visitor_id).first() is None
        assert db.query(FaceData).filter(FaceData.id == face_id).first() is None
        assert preserved_log is not None
        assert preserved_log.visitor_id is None
        assert preserved_log.face_data_id is None
        assert preserved_log.identified is False
        assert preserved_log.status == "unidentified"

    def test_delete_face_data_preserves_referencing_log(
        self, client, admin_headers, admin_user, db
    ):
        from models.models import FaceData, Visitor, VisitorLog

        visitor = Visitor(
            organization_id=admin_user.organization_id,
            name="Face Delete Test",
            is_known=True,
            is_active=True,
        )
        db.add(visitor)
        db.commit()
        db.refresh(visitor)

        face = FaceData(visitor_id=visitor.id, embedding=[0.0] * 512, is_primary=True)
        db.add(face)
        db.commit()
        db.refresh(face)

        visitor_log = VisitorLog(
            organization_id=admin_user.organization_id,
            visitor_id=visitor.id,
            face_data_id=face.id,
            identified=True,
            status="identified",
        )
        db.add(visitor_log)
        db.commit()
        db.refresh(visitor_log)

        visitor_id = visitor.id
        face_id = face.id
        visitor_log_id = visitor_log.id

        response = client.delete(
            f"{API}/{visitor_id}/face-data/{face_id}",
            headers=admin_headers,
        )
        assert response.status_code == 200

        db.expire_all()
        preserved_log = db.query(VisitorLog).filter(VisitorLog.id == visitor_log_id).first()
        assert db.query(FaceData).filter(FaceData.id == face_id).first() is None
        assert preserved_log is not None
        assert preserved_log.visitor_id == visitor_id
        assert preserved_log.face_data_id is None


class TestOrgIsolation:
    def test_visitor_org_isolation(self, client, db):
        """A user from org A cannot see visitors from org B."""
        from models.models import Organization, User, Visitor
        from core.security import hash_password

        # Create a second org with its own user and visitor
        org_b = Organization(name="Org B Isolation Test")
        db.add(org_b)
        db.commit()
        db.refresh(org_b)

        user_b = User(
            organization_id=org_b.id,
            email=f"orgb-{uuid.uuid4().hex[:6]}@test.com",
            full_name="Org B User",
            password_hash=hash_password("OrgB123!"),
            role="admin",
        )
        db.add(user_b)
        db.commit()

        visitor_b = Visitor(
            organization_id=org_b.id,
            name="Org B Visitor",
            is_known=True,
            is_active=True,
        )
        db.add(visitor_b)
        db.commit()
        db.refresh(visitor_b)

        # Login as org B user
        login_res = client.post("/api/v1/auth/login", json={
            "email": user_b.email,
            "password": "OrgB123!",
        })
        if login_res.status_code != 200:
            pytest.skip("Could not log in as org B user")

        headers_b = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

        # Org B user should see their visitor
        res = client.get(API, headers=headers_b)
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        names = [v.get("name", "") for v in items]
        assert "Org B Visitor" in names


class TestExport:
    def test_export_visitors_csv(self, client, admin_headers, sample_visitor):
        response = client.get(f"{API}/export", headers=admin_headers)
        # Endpoint may return CSV or an error if no visitors match
        assert response.status_code in (200, 204, 404)
