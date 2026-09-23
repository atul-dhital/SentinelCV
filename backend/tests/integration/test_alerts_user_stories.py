"""
Acceptance tests for the /alerts page user stories (ALERT-001 … ALERT-009).

These tests exercise the full HTTP path end-to-end (router → service → DB)
through the shared FastAPI TestClient fixture so we verify that the new
frontend Alerts page has working backend contracts.

Mapping:
  ALERT-001  Create alert rule            POST /alerts/rules
  ALERT-002  Configure thresholds         GET/PUT /alerts/config
  ALERT-003  List alert rules             GET  /alerts/rules
  ALERT-004  Update an alert rule         PUT  /alerts/rules/{id}
  ALERT-005  Activate/deactivate a rule   POST /alerts/rules/{id}/activate
                                          POST /alerts/rules/{id}/deactivate
  ALERT-006  Delete a rule                DELETE /alerts/rules/{id}
  ALERT-007  Reorder rules                POST /alerts/rules/reorder
  ALERT-008  View stats                   GET  /alerts/stats
  ALERT-009  View recent triggers         GET  /alerts/triggers
"""

from __future__ import annotations

API = "/api/v1/alerts"


# ── ALERT-002 Config GET + PUT ──────────────────────────────────────────────


def test_alert_002_config_get_creates_default(client, admin_headers):
    resp = client.get(f"{API}/config", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "alerts_enabled",
        "email_alerts_enabled",
        "webhook_alerts_enabled",
        "min_confidence_threshold",
        "alert_duplicate_window_seconds",
        "enabled_alert_types",
        "default_action",
    ):
        assert key in body, f"missing key: {key}"
    assert 0.0 <= body["min_confidence_threshold"] <= 1.0


def test_alert_002_config_put_persists(client, admin_headers):
    payload = {
        "alerts_enabled": True,
        "email_alerts_enabled": False,
        "webhook_alerts_enabled": True,
        "min_confidence_threshold": 0.75,
        "alert_duplicate_window_seconds": 120,
        "enabled_alert_types": ["unknown", "liveness_failed"],
        "default_action": "webhook",
    }
    put_resp = client.put(f"{API}/config", headers=admin_headers, json=payload)
    assert put_resp.status_code == 200, put_resp.text
    updated = put_resp.json()
    assert updated["email_alerts_enabled"] is False
    assert updated["min_confidence_threshold"] == 0.75
    assert updated["default_action"] == "webhook"
    assert "unknown" in updated["enabled_alert_types"]

    refetched = client.get(f"{API}/config", headers=admin_headers).json()
    assert refetched["min_confidence_threshold"] == 0.75
    assert refetched["alert_duplicate_window_seconds"] == 120


# ── ALERT-001/003/004/006 Rules CRUD cycle ──────────────────────────────────


def test_alert_rules_full_crud_cycle(client, admin_headers):
    # 1. Starting list
    list_resp = client.get(f"{API}/rules", headers=admin_headers)
    assert list_resp.status_code == 200, list_resp.text
    starting = list_resp.json()
    assert isinstance(starting, list)

    # 2. Create
    payload = {
        "name": "Acceptance test rule",
        "description": "Created by acceptance tests",
        "is_active": True,
        "priority": "high",
        "trigger_type": "unknown",
        "min_confidence": 0.65,
        "action": "email",
        "max_alerts_per_hour": 10,
    }
    create_resp = client.post(f"{API}/rules", headers=admin_headers, json=payload)
    assert create_resp.status_code == 200, create_resp.text
    created = create_resp.json()
    assert created["name"] == "Acceptance test rule"
    assert created["trigger_type"] == "unknown"
    assert created["is_active"] is True
    assert created["min_confidence"] == 0.65
    rule_id = created["id"]

    # 3. List should contain it
    listed = client.get(f"{API}/rules", headers=admin_headers).json()
    assert any(r["id"] == rule_id for r in listed)
    assert len(listed) == len(starting) + 1

    # 4. Get by id
    get_resp = client.get(f"{API}/rules/{rule_id}", headers=admin_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == rule_id

    # 5. Update
    update_payload = {"min_confidence": 0.85, "priority": "critical"}
    update_resp = client.put(
        f"{API}/rules/{rule_id}", headers=admin_headers, json=update_payload
    )
    assert update_resp.status_code == 200, update_resp.text
    updated = update_resp.json()
    assert updated["min_confidence"] == 0.85
    assert updated["priority"] == "critical"

    # 6. Delete
    del_resp = client.delete(f"{API}/rules/{rule_id}", headers=admin_headers)
    assert del_resp.status_code == 200, del_resp.text

    # 7. Gone
    final = client.get(f"{API}/rules", headers=admin_headers).json()
    assert not any(r["id"] == rule_id for r in final)


# ── ALERT-005 Activate / deactivate ─────────────────────────────────────────


def test_alert_005_activate_and_deactivate(client, admin_headers):
    create = client.post(
        f"{API}/rules",
        headers=admin_headers,
        json={
            "name": "Toggle test",
            "is_active": True,
            "priority": "medium",
            "trigger_type": "known",
            "action": "notify",
        },
    )
    assert create.status_code == 200, create.text
    rule_id = create.json()["id"]

    # Deactivate
    deact = client.post(f"{API}/rules/{rule_id}/deactivate", headers=admin_headers)
    assert deact.status_code == 200
    assert deact.json()["is_active"] is False

    # Reactivate
    act = client.post(f"{API}/rules/{rule_id}/activate", headers=admin_headers)
    assert act.status_code == 200
    assert act.json()["is_active"] is True

    # Cleanup
    client.delete(f"{API}/rules/{rule_id}", headers=admin_headers)


# ── ALERT-003 List filter by is_active ──────────────────────────────────────


def test_alert_003_list_filter_by_is_active(client, admin_headers):
    active_rule = client.post(
        f"{API}/rules",
        headers=admin_headers,
        json={
            "name": "Active filter",
            "is_active": True,
            "priority": "low",
            "trigger_type": "anomaly",
            "action": "silence",
        },
    ).json()
    paused_rule = client.post(
        f"{API}/rules",
        headers=admin_headers,
        json={
            "name": "Paused filter",
            "is_active": False,
            "priority": "low",
            "trigger_type": "anomaly",
            "action": "silence",
        },
    ).json()

    active_list = client.get(
        f"{API}/rules", headers=admin_headers, params={"is_active": True}
    ).json()
    paused_list = client.get(
        f"{API}/rules", headers=admin_headers, params={"is_active": False}
    ).json()

    assert any(r["id"] == active_rule["id"] for r in active_list)
    assert all(r["is_active"] for r in active_list)
    assert any(r["id"] == paused_rule["id"] for r in paused_list)
    assert all(not r["is_active"] for r in paused_list)

    client.delete(f"{API}/rules/{active_rule['id']}", headers=admin_headers)
    client.delete(f"{API}/rules/{paused_rule['id']}", headers=admin_headers)


# ── ALERT-007 Reorder ───────────────────────────────────────────────────────


def test_alert_007_reorder_rules(client, admin_headers):
    created_ids = []
    for name in ("Alpha", "Bravo", "Charlie"):
        rule = client.post(
            f"{API}/rules",
            headers=admin_headers,
            json={
                "name": f"Reorder {name}",
                "is_active": True,
                "priority": "medium",
                "trigger_type": "unknown",
                "action": "email",
            },
        ).json()
        created_ids.append(rule["id"])

    reversed_order = list(reversed(created_ids))
    resp = client.post(
        f"{API}/rules/reorder", headers=admin_headers, json=reversed_order
    )
    assert resp.status_code == 200, resp.text

    for rid in created_ids:
        client.delete(f"{API}/rules/{rid}", headers=admin_headers)


# ── ALERT-008 Stats endpoint ────────────────────────────────────────────────


def test_alert_008_stats_endpoint(client, admin_headers):
    # Ensure at least one rule exists
    created = client.post(
        f"{API}/rules",
        headers=admin_headers,
        json={
            "name": "Stats fixture",
            "is_active": True,
            "priority": "medium",
            "trigger_type": "unknown",
            "action": "email",
        },
    ).json()

    resp = client.get(f"{API}/stats", headers=admin_headers, params={"days": 7})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    for key in ("organization_id", "alerts_enabled", "total_rules", "active_rules", "by_trigger_type"):
        assert key in body, f"missing key: {key}"
    assert body["total_rules"] >= 1
    assert body["active_rules"] >= 1
    assert isinstance(body["by_trigger_type"], dict)

    client.delete(f"{API}/rules/{created['id']}", headers=admin_headers)


# ── ALERT-009 Triggers endpoint ─────────────────────────────────────────────


def test_alert_009_triggers_endpoint(client, admin_headers):
    resp = client.get(f"{API}/triggers", headers=admin_headers, params={"days": 7})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    # With a fresh DB the list is empty; we only validate the structure contract.
    for item in body:
        for key in ("id", "alert_type", "message"):
            assert key in item
