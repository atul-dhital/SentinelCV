from models.models import Webhook


def test_organization_me_hides_api_key(client, admin_headers):
    response = client.get("/api/v1/organizations/me", headers=admin_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["name"]
    assert "api_key" not in payload


def test_staff_cannot_access_webhook_admin_surfaces(client, db, staff_headers, test_org):
    webhook = Webhook(
        organization_id=test_org.id,
        url="https://example.com/webhook",
        secret="test-secret",
        events=["visitor.identified"],
        is_active=True,
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)

    list_response = client.get("/api/v1/webhooks/", headers=staff_headers)
    test_response = client.post(f"/api/v1/webhooks/{webhook.id}/test", headers=staff_headers)
    logs_response = client.get(f"/api/v1/webhooks/{webhook.id}/logs", headers=staff_headers)
    api_keys_response = client.get("/api/v1/webhooks/api-keys", headers=staff_headers)

    assert list_response.status_code == 403, list_response.text
    assert test_response.status_code == 403, test_response.text
    assert logs_response.status_code == 403, logs_response.text
    assert api_keys_response.status_code == 403, api_keys_response.text


def test_staff_cannot_mutate_alerts_or_compliance(client, staff_headers, sample_visitor):
    alert_response = client.put(
        "/api/v1/alerts/config",
        headers=staff_headers,
        json={"alerts_enabled": False},
    )
    retention_response = client.get(
        "/api/v1/compliance/retention-policies",
        headers=staff_headers,
    )
    export_response = client.get(
        f"/api/v1/compliance/gdpr/export/{sample_visitor.id}",
        headers=staff_headers,
    )
    delete_response = client.delete(
        f"/api/v1/compliance/gdpr/delete/{sample_visitor.id}",
        headers=staff_headers,
    )

    assert alert_response.status_code == 403, alert_response.text
    assert retention_response.status_code == 403, retention_response.text
    assert export_response.status_code == 403, export_response.text
    assert delete_response.status_code == 403, delete_response.text


def test_admin_can_create_and_list_retention_policies(client, admin_headers):
    create_response = client.post(
        "/api/v1/compliance/retention-policies",
        headers=admin_headers,
        json={
            "entity_type": "audit_logs",
            "retention_days": 30,
            "auto_delete": True,
        },
    )

    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    assert created["entity_type"] == "audit_logs"
    assert created["retention_days"] == 30
    assert created["auto_delete"] is True
    assert created["last_cleanup_at"] is None

    list_response = client.get("/api/v1/compliance/retention-policies", headers=admin_headers)
    assert list_response.status_code == 200, list_response.text
    listed = list_response.json()
    assert len(listed) == 1
    assert listed[0]["entity_type"] == "audit_logs"

    cleanup_response = client.post("/api/v1/compliance/retention-cleanup", headers=admin_headers)
    assert cleanup_response.status_code == 200, cleanup_response.text
    cleanup_payload = cleanup_response.json()
    assert cleanup_payload[0]["entity_type"] == "audit_logs"
