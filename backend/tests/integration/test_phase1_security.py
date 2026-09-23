"""Integration tests for Phase 1 security fixes.

Covers:
- Password reset token hashing (token stored as SHA-256 hash, not plain text)
- SSO configure requires admin role
- SSO update/delete requires admin role
- SSO ACS returns real JWT access+refresh token
- GDPR export requires admin role
- GDPR delete requires admin role
- GDPR cleanup requires admin role
"""

import hashlib
import uuid as _uuid

import pytest

from models.models import Organization, PasswordResetToken, SSOProvider, User, Visitor
from core.security import hash_password

AUTH = "/api/v1/auth"
SSO = "/api/v1/sso"
GDPR = "/api/v1/gdpr"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _login(client, email: str, password: str) -> str:
    res = client.post(f"{AUTH}/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _set_minimal_production_env(monkeypatch):
    monkeypatch.setenv("SENTINELCV_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://sentinelcv:password@db:5432/sentinelcv")
    monkeypatch.setenv("SECRET_KEY", "prod-secret-key-0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("EMBEDDING_KEY_SECRET", "prod-embedding-key-abcdef0123456789abcdef01234567")
    monkeypatch.setenv("METRICS_TOKEN", "prod-metrics-token-abcdef0123456789abcdef0123")
    monkeypatch.setenv("INTERNAL_SERVICE_KEY", "prod-internal-key-abcdef0123456789abcdef0123")
    monkeypatch.setenv("ALLOWED_HOSTS", "sentinelcv.example.com")
    monkeypatch.setenv("ENFORCE_TENANT_FILTER", "1")
    monkeypatch.setenv("STORAGE_TYPE", "s3")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "sentinelcv-prod-media")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT_URL", "https://s3.example.com")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY_ID", "prod-access-key")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_ACCESS_KEY", "prod-secret-key")


class TestProductionStartupGuards:
    def test_production_requires_internal_service_key(self, monkeypatch):
        import main as main_module

        _set_minimal_production_env(monkeypatch)
        monkeypatch.delenv("INTERNAL_SERVICE_KEY", raising=False)

        with pytest.raises(SystemExit):
            main_module._validate_startup_env("postgresql://sentinelcv:password@db:5432/sentinelcv")

    @pytest.mark.parametrize(
        "flag_name, flag_value",
        [
            ("ENFORCE_TENANT_FILTER", "0"),
            ("ALLOW_SYNTHETIC_BIOMETRIC_FALLBACK", "1"),
            ("ALLOW_PRIVATE_RTSP_TARGETS", "1"),
            ("SKIP_USER_PATH_EXISTS_CHECK", "1"),
            ("ENABLE_EXPERIMENTAL_FEATURES", "1"),
            ("ENABLE_PHASE3_FEATURES", "1"),
        ],
    )
    def test_production_rejects_test_only_flags(self, monkeypatch, flag_name, flag_value):
        import main as main_module

        _set_minimal_production_env(monkeypatch)
        monkeypatch.setenv(flag_name, flag_value)

        with pytest.raises(SystemExit):
            main_module._validate_startup_env("postgresql://sentinelcv:password@db:5432/sentinelcv")

    @pytest.mark.parametrize("allowed_hosts", [None, "*"])
    def test_production_requires_safe_allowed_hosts(self, monkeypatch, allowed_hosts):
        import main as main_module

        _set_minimal_production_env(monkeypatch)
        if allowed_hosts is None:
            monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
        else:
            monkeypatch.setenv("ALLOWED_HOSTS", allowed_hosts)

        with pytest.raises(SystemExit):
            main_module._validate_startup_env("postgresql://sentinelcv:password@db:5432/sentinelcv")

    def test_production_rejects_local_only_media_storage(self, monkeypatch):
        import main as main_module

        _set_minimal_production_env(monkeypatch)
        monkeypatch.setenv("STORAGE_TYPE", "local")

        with pytest.raises(SystemExit):
            main_module._validate_startup_env("postgresql://sentinelcv:password@db:5432/sentinelcv")


# ── Password reset token hashing ──────────────────────────────────────────────


class TestPasswordResetHashing:
    def test_forgot_password_stores_hash_not_plain(self, client, admin_user, db, monkeypatch):
        """The DB row must contain SHA-256(token), not the raw token."""
        captured = {}

        def fake_send(email, token):
            captured["plain_token"] = token
            return True, "sent"

        monkeypatch.setattr(
            "api.auth.password_reset_email_service.send_password_reset_email",
            fake_send,
        )

        res = client.post(f"{AUTH}/forgot-password", json={"email": admin_user.email})
        assert res.status_code == 200, res.text

        plain = captured["plain_token"]
        assert plain, "Email service was not called"

        expected_hash = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        record = (
            db.query(PasswordResetToken)
            .filter(PasswordResetToken.user_id == admin_user.id)
            .order_by(PasswordResetToken.created_at.desc())
            .first()
        )
        assert record is not None, "No PasswordResetToken created"
        assert record.token == expected_hash, "token column should be SHA-256 hash"
        assert record.token != plain, "plain token must NOT be stored"

    def test_reset_password_with_plain_token_succeeds(self, client, admin_user, db, monkeypatch):
        """Submitting the plain token from the email must update the password."""
        captured = {}

        def fake_send(email, token):
            captured["plain_token"] = token
            return True, "sent"

        monkeypatch.setattr(
            "api.auth.password_reset_email_service.send_password_reset_email",
            fake_send,
        )
        client.post(f"{AUTH}/forgot-password", json={"email": admin_user.email})
        plain = captured["plain_token"]

        res = client.post(
            f"{AUTH}/reset-password",
            json={"token": plain, "new_password": "NewSecure456!"},
        )
        assert res.status_code == 200, res.text
        assert "reset successfully" in res.json()["message"].lower()

    def test_reset_password_wrong_token_rejected(self, client, admin_user, db):
        """Submitting a token that was never issued must be rejected with 400.

        Does not call forgot-password (avoids rate-limit interference).
        The schema requires a minimum-length password so we use a valid one.
        """
        res = client.post(
            f"{AUTH}/reset-password",
            json={"token": "this-token-was-never-issued-12345", "new_password": "ValidPass123!"},
        )
        assert res.status_code == 400

    def test_reset_token_single_use(self, client, admin_user, db, monkeypatch):
        """After one successful reset, the same token must be rejected."""
        captured = {}

        def fake_send(email, token):
            captured["plain_token"] = token
            return True, "sent"

        monkeypatch.setattr(
            "api.auth.password_reset_email_service.send_password_reset_email",
            fake_send,
        )
        client.post(f"{AUTH}/forgot-password", json={"email": admin_user.email})
        plain = captured["plain_token"]

        client.post(
            f"{AUTH}/reset-password",
            json={"token": plain, "new_password": "FirstReset123!"},
        )
        # Second use of the same token
        res = client.post(
            f"{AUTH}/reset-password",
            json={"token": plain, "new_password": "SecondReset123!"},
        )
        assert res.status_code == 400

    def test_expired_reset_token_rejected(self, client, admin_user, db, monkeypatch):
        """An expired token must not be accepted even if used is False."""
        from datetime import datetime, timedelta, timezone

        def fake_send(email, token):
            return True, "sent"

        monkeypatch.setattr(
            "api.auth.password_reset_email_service.send_password_reset_email",
            fake_send,
        )

        plain = "test-expired-token-value-unique"
        expired_hash = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        record = PasswordResetToken(
            user_id=admin_user.id,
            token=expired_hash,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
            used=False,
        )
        db.add(record)
        db.commit()

        res = client.post(
            f"{AUTH}/reset-password",
            json={"token": plain, "new_password": "ShouldFail123!"},
        )
        assert res.status_code == 400
        assert "expired" in res.json()["detail"].lower()


# ── SSO configure admin guard ─────────────────────────────────────────────────


class TestSSOConfigureAdminGuard:
    _provider_body = {
        "provider_type": "saml",
        "provider_name": "Phase1 IdP",
        "entity_id": "https://phase1-idp.example.com",
        "sso_url": "https://phase1-idp.example.com/sso",
        "certificate": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----",
        "attribute_mappings": {"email": "email"},
        "active": True,
    }

    def test_staff_cannot_configure_sso(self, client, staff_headers):
        res = client.post(f"{SSO}/configure", json=self._provider_body, headers=staff_headers)
        assert res.status_code == 403, res.text

    def test_unauthenticated_cannot_configure_sso(self, client):
        res = client.post(f"{SSO}/configure", json=self._provider_body)
        assert res.status_code == 401, res.text

    def test_admin_can_configure_sso(self, client, admin_headers):
        body = {**self._provider_body, "provider_name": f"AdminIdP-{_uuid.uuid4().hex[:6]}",
                "entity_id": f"https://idp-{_uuid.uuid4().hex[:6]}.example.com"}
        res = client.post(f"{SSO}/configure", json=body, headers=admin_headers)
        assert res.status_code == 201, res.text


class TestSSOUpdateDeleteAdminGuard:
    def _create_provider(self, client, admin_headers) -> str:
        uid = _uuid.uuid4().hex[:6]
        res = client.post(
            f"{SSO}/configure",
            json={
                "provider_type": "saml",
                "provider_name": f"UpdDel-{uid}",
                "entity_id": f"https://upddel-{uid}.example.com",
                "sso_url": f"https://upddel-{uid}.example.com/sso",
                "certificate": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----",
                "attribute_mappings": {},
                "active": True,
            },
            headers=admin_headers,
        )
        assert res.status_code == 201, res.text
        return res.json()["id"]

    def test_staff_cannot_update_sso_provider(self, client, admin_headers, staff_headers):
        pid = self._create_provider(client, admin_headers)
        res = client.put(
            f"{SSO}/providers/{pid}",
            json={"provider_name": "Hacked"},
            headers=staff_headers,
        )
        assert res.status_code == 403, res.text

    def test_staff_cannot_delete_sso_provider(self, client, admin_headers, staff_headers):
        pid = self._create_provider(client, admin_headers)
        res = client.delete(f"{SSO}/providers/{pid}", headers=staff_headers)
        assert res.status_code == 403, res.text

    def test_admin_can_update_sso_provider(self, client, admin_headers):
        pid = self._create_provider(client, admin_headers)
        res = client.put(
            f"{SSO}/providers/{pid}",
            json={"provider_name": "UpdatedName"},
            headers=admin_headers,
        )
        assert res.status_code == 200, res.text

    def test_admin_can_delete_sso_provider(self, client, admin_headers):
        pid = self._create_provider(client, admin_headers)
        res = client.delete(f"{SSO}/providers/{pid}", headers=admin_headers)
        assert res.status_code == 204, res.text

    def test_staff_can_list_sso_providers(self, client, staff_headers):
        """Read access to provider list must remain open to all authenticated users."""
        res = client.get(f"{SSO}/providers", headers=staff_headers)
        assert res.status_code == 200, res.text


# ── SSO ACS returns real JWT ──────────────────────────────────────────────────


class TestSSO_ACS_JWT:
    def _make_saml_b64(self, issuer: str, email: str) -> str:
        import base64
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol">'
            f'<saml:Issuer xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">{issuer}</saml:Issuer>'
            '<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
            f'<saml:Subject><saml:NameID>{email}</saml:NameID></saml:Subject>'
            '<saml:AttributeStatement>'
            '<saml:Attribute Name="email">'
            f'<saml:AttributeValue>{email}</saml:AttributeValue>'
            "</saml:Attribute>"
            "</saml:AttributeStatement>"
            "</saml:Assertion>"
            "</samlp:Response>"
        )
        return base64.b64encode(xml.encode()).decode()

    def _create_provider(self, client, admin_headers) -> dict:
        uid = _uuid.uuid4().hex[:6]
        res = client.post(
            f"{SSO}/configure",
            json={
                "provider_type": "saml",
                "provider_name": f"ACSTest-{uid}",
                "entity_id": f"https://acs-{uid}.example.com",
                "sso_url": f"https://acs-{uid}.example.com/sso",
                "certificate": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----",
                "attribute_mappings": {"email": "email"},
                "active": True,
            },
            headers=admin_headers,
        )
        assert res.status_code == 201, res.text
        return res.json()

    def test_acs_returns_jwt_not_fake_session_token(self, client, admin_headers, admin_user):
        """Phase 1 fix: ACS must issue a real JWT access+refresh pair."""
        provider = self._create_provider(client, admin_headers)
        res = client.post(
            f"{SSO}/acs",
            json={
                "provider_id": provider["id"],
                "saml_response": self._make_saml_b64(
                    provider["entity_id"], admin_user.email
                ),
                "relay_state": "dashboard",
            },
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["authenticated"] is True
        assert "access_token" in data, "access_token must be present"
        assert "refresh_token" in data, "refresh_token must be present"
        assert data["token_type"] == "bearer"
        assert "session_token" not in data, "legacy session_token must be absent"

    def test_acs_access_token_is_usable(self, client, admin_headers, admin_user):
        """The issued access token must authenticate subsequent API calls."""
        provider = self._create_provider(client, admin_headers)
        acs_res = client.post(
            f"{SSO}/acs",
            json={
                "provider_id": provider["id"],
                "saml_response": self._make_saml_b64(
                    provider["entity_id"], admin_user.email
                ),
            },
        )
        assert acs_res.status_code == 200, acs_res.text
        token = acs_res.json()["access_token"]

        me_res = client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200, me_res.text
        assert me_res.json()["email"] == admin_user.email


# ── GDPR admin guards ─────────────────────────────────────────────────────────


class TestGDPRAdminGuards:
    def _make_visitor(self, db, org_id) -> Visitor:
        v = Visitor(
            organization_id=org_id,
            name=f"GDPR-Guard-{_uuid.uuid4().hex[:6]}",
            email=f"gdpr-guard-{_uuid.uuid4().hex[:6]}@test.com",
            is_known=True,
            is_active=True,
        )
        db.add(v)
        db.commit()
        db.refresh(v)
        return v

    def test_staff_cannot_request_gdpr_export(self, client, staff_headers, db, admin_user):
        v = self._make_visitor(db, admin_user.organization_id)
        res = client.post(f"{GDPR}/export?visitor_id={v.id}", headers=staff_headers)
        assert res.status_code == 403, res.text

    def test_staff_cannot_request_gdpr_delete(self, client, staff_headers, db, admin_user):
        v = self._make_visitor(db, admin_user.organization_id)
        res = client.post(f"{GDPR}/delete?visitor_id={v.id}", headers=staff_headers)
        assert res.status_code == 403, res.text

    def test_staff_cannot_trigger_gdpr_cleanup(self, client, staff_headers, admin_user):
        res = client.post(
            f"{GDPR}/cleanup/{admin_user.organization_id}", headers=staff_headers
        )
        assert res.status_code == 403, res.text

    def test_staff_cannot_update_retention_policies(self, client, staff_headers, admin_user):
        payload = [{"data_type": "face_images", "retention_days": 30, "auto_delete_enabled": True}]
        res = client.put(
            f"{GDPR}/policies/{admin_user.organization_id}",
            json=payload,
            headers=staff_headers,
        )
        assert res.status_code == 403, res.text

    def test_staff_cannot_read_retention_policies(self, client, staff_headers, admin_user):
        res = client.get(
            f"{GDPR}/policies/{admin_user.organization_id}", headers=staff_headers
        )
        assert res.status_code == 403, res.text

    def test_admin_can_update_retention_policies(self, client, admin_headers, admin_user):
        payload = [{"data_type": "face_images", "retention_days": 60, "auto_delete_enabled": False}]
        res = client.put(
            f"{GDPR}/policies/{admin_user.organization_id}",
            json=payload,
            headers=admin_headers,
        )
        assert res.status_code == 201, res.text

    def test_admin_can_read_retention_policies(self, client, admin_headers, admin_user):
        res = client.get(
            f"{GDPR}/policies/{admin_user.organization_id}", headers=admin_headers
        )
        assert res.status_code == 200, res.text

    def test_unauthenticated_cannot_export_gdpr(self, client, db, admin_user):
        v = self._make_visitor(db, admin_user.organization_id)
        res = client.post(f"{GDPR}/export?visitor_id={v.id}")
        assert res.status_code == 401, res.text
