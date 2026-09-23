from core.security import hash_password
from models.models import User


BASE = "/api/v1/ldap"


def _create_ldap_config(client, admin_headers, **overrides):
    payload = {
        "ldap_server": "ldaps://directory.example.com",
        "ldap_port": 636,
        "use_ssl": True,
        "bind_dn": "cn=service,dc=example,dc=com",
        "bind_password": "super-secret",
        "user_search_base": "ou=users,dc=example,dc=com",
        "group_search_base": "ou=groups,dc=example,dc=com",
        "user_attribute": "mail",
        "group_attribute": "cn",
        "active": True,
    }
    payload.update(overrides)
    response = client.post(f"{BASE}/config", json=payload, headers=admin_headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_ldap_test_endpoint_validates_ready_config(client, admin_headers):
    config = _create_ldap_config(client, admin_headers)

    response = client.post(f"{BASE}/config/{config['id']}/test", headers=admin_headers)
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["details"]["sync_ready"] is True
    assert payload["details"]["validation_errors"] == []
    assert payload["details"]["normalized_url"] == "ldaps://directory.example.com:636"


def test_ldap_test_endpoint_rejects_incomplete_active_config(client, admin_headers):
    config = _create_ldap_config(
        client,
        admin_headers,
        bind_dn=None,
        bind_password=None,
    )

    response = client.post(f"{BASE}/config/{config['id']}/test", headers=admin_headers)
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["status"] == "failed"
    assert "bind_dn" in payload["message"]
    assert "active sync requires bind_dn" in payload["details"]["validation_errors"]
    assert "active sync requires bind_password" in payload["details"]["validation_errors"]


def test_ldap_sync_returns_org_user_counts_and_logs_result(client, admin_headers, admin_user, db):
    db.add(
        User(
            organization_id=admin_user.organization_id,
            email="ldap-analyst@test.com",
            full_name="LDAP Analyst",
            password_hash=hash_password("Analyst123!"),
            role="analyst",
            is_active=True,
        )
    )
    db.add(
        User(
            organization_id=admin_user.organization_id,
            email="ldap-disabled@test.com",
            full_name="LDAP Disabled",
            password_hash=hash_password("Disabled123!"),
            role="staff",
            is_active=False,
        )
    )
    db.commit()

    config = _create_ldap_config(client, admin_headers)

    response = client.post(f"{BASE}/config/{config['id']}/sync", headers=admin_headers)
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["status"] == "success"
    assert payload["users_synced"] == 2
    assert payload["groups_synced"] == 2
    assert payload["users_disabled"] == 1
    assert "validated 2 active user(s)" in payload["message"]

    logs_response = client.get(f"{BASE}/sync-logs", headers=admin_headers)
    assert logs_response.status_code == 200, logs_response.text
    logs_payload = logs_response.json()
    assert logs_payload["total"] >= 1
    assert logs_payload["items"][0]["status"] == "success"
