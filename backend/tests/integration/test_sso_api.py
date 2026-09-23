import base64


BASE = "/api/v1/sso"


def _encode_saml_response(issuer: str, email: str, name: str) -> str:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol">
  <saml:Issuer xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">{issuer}</saml:Issuer>
  <saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">
    <saml:Subject>
      <saml:NameID>{email}</saml:NameID>
    </saml:Subject>
    <saml:AttributeStatement>
      <saml:Attribute Name="email">
        <saml:AttributeValue>{email}</saml:AttributeValue>
      </saml:Attribute>
      <saml:Attribute Name="name">
        <saml:AttributeValue>{name}</saml:AttributeValue>
      </saml:Attribute>
    </saml:AttributeStatement>
  </saml:Assertion>
</samlp:Response>
"""
    return base64.b64encode(xml.encode("utf-8")).decode("utf-8")


def _create_saml_provider(client, admin_headers):
    response = client.post(
        f"{BASE}/configure",
        json={
            "provider_type": "saml",
            "provider_name": "Example IdP",
            "entity_id": "https://idp.example.com",
            "sso_url": "https://idp.example.com/sso",
            "certificate": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----",
            "attribute_mappings": {"email": "email", "name": "name"},
            "active": True,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def test_generate_saml_metadata(client, admin_headers):
    provider = _create_saml_provider(client, admin_headers)
    response = client.get(
        f"{BASE}/metadata",
        params={"provider_id": provider["id"]},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert provider["entity_id"] in response.text
    assert "/api/v1/sso/acs" in response.text


def test_saml_acs_authenticates_existing_user(client, admin_headers):
    provider = _create_saml_provider(client, admin_headers)
    response = client.post(
        f"{BASE}/acs",
        json={
            "provider_id": provider["id"],
            "saml_response": _encode_saml_response(
                "https://idp.example.com",
                "admin@test.com",
                "Test Admin",
            ),
            "relay_state": "dashboard",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert data["email"] == "admin@test.com"
    # Phase 1 fix: ACS now issues a real JWT access+refresh pair, not a fake session token.
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert "session_token" not in data
    assert data["relay_state"] == "dashboard"


def test_saml_acs_rejects_invalid_issuer(client, admin_headers):
    provider = _create_saml_provider(client, admin_headers)
    response = client.post(
        f"{BASE}/acs",
        json={
            "provider_id": provider["id"],
            "saml_response": _encode_saml_response(
                "https://unexpected-idp.example.com",
                "admin@test.com",
                "Test Admin",
            ),
        },
    )
    assert response.status_code == 400


def test_saml_acs_reports_unprovisioned_user(client, admin_headers):
    provider = _create_saml_provider(client, admin_headers)
    response = client.post(
        f"{BASE}/acs",
        json={
            "provider_id": provider["id"],
            "saml_response": _encode_saml_response(
                "https://idp.example.com",
                "new.user@example.com",
                "New User",
            ),
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is False
    assert data["reason"] == "user_not_provisioned"
