"""
Acceptance tests for the /future-enhancements page user stories (ENH-001 … ENH-008).

Each test exercises the full HTTP path end-to-end (router → service → DB)
through the shared FastAPI TestClient fixture so we verify that the frontend
Future Enhancements dashboard has working backend contracts.

Mapping:
  ENH-001  Roadmap overview               GET  /future-enhancements/roadmap/overview
  ENH-002  Augmentation config            GET/PUT /future-enhancements/config/augmentation
  ENH-003  Model architecture config      GET/PUT /future-enhancements/config/model-architecture
  ENH-004  Current capabilities           GET  /future-enhancements/capabilities/current
  ENH-005  Priority matrix                GET  /future-enhancements/priority-matrix
  ENH-006  Metrics targets                GET  /future-enhancements/metrics/targets
  ENH-007  Bias audit                     GET  /future-enhancements/audit/bias
  ENH-008  Rate limits CRUD               GET/POST/PUT/DELETE /future-enhancements/rate-limits/
"""

from __future__ import annotations

import pytest

API = "/api/v1/future-enhancements"


# ── ENH-001 Roadmap Overview ────────────────────────────────────────────────


def test_enh_001_roadmap_overview_returns_phases_and_counts(client, admin_headers):
    resp = client.get(f"{API}/roadmap/overview", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "phases" in body and isinstance(body["phases"], list)
    assert len(body["phases"]) == 4  # short_term, medium_term, long_term, future_ready
    phase_keys = {p["phase"] for p in body["phases"]}
    assert phase_keys == {"short_term", "medium_term", "long_term", "future_ready"}

    assert "total_enhancements" in body
    assert "enabled_count" in body
    assert "completion_percent" in body
    assert body["total_enhancements"] >= 0
    assert 0 <= body["completion_percent"] <= 100

    # Every phase returns its metadata tasks
    for phase in body["phases"]:
        assert phase["title"]
        assert phase["description"]
        assert phase["timeline"]
        assert isinstance(phase["tasks"], list)
        assert isinstance(phase["enhancements"], list)


# ── ENH-002 Augmentation Config GET + PUT ───────────────────────────────────


def test_enh_002_augmentation_config_get_returns_six_techniques(client, admin_headers):
    resp = client.get(f"{API}/config/augmentation", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    techniques = body["techniques"]
    names = {t["technique"] for t in techniques}
    assert names == {
        "cutmix",
        "mixup",
        "adversarial",
        "random_erasing",
        "geometric",
        "color_jitter",
    }
    assert "quality_checks_enabled" in body
    assert "auto_balance_demographics" in body
    assert isinstance(body["data_quality_actions"], list)
    assert len(body["data_quality_actions"]) >= 1


def test_enh_002_augmentation_config_put_persists(client, admin_headers):
    # First fetch the current state so we can round-trip it
    original = client.get(f"{API}/config/augmentation", headers=admin_headers).json()

    payload = {
        "techniques": [
            {
                "technique": "cutmix",
                "enabled": True,
                "params": {"alpha": 1.5},
                "description": "test",
            },
            {
                "technique": "mixup",
                "enabled": True,
                "params": {"alpha": 0.4},
                "description": "test",
            },
            {
                "technique": "adversarial",
                "enabled": False,
                "params": {"epsilon": 0.03},
                "description": "test",
            },
            {
                "technique": "random_erasing",
                "enabled": False,
                "params": {"probability": 0.5},
                "description": "test",
            },
            {
                "technique": "geometric",
                "enabled": True,
                "params": {"rotation_range": 45},
                "description": "test",
            },
            {
                "technique": "color_jitter",
                "enabled": False,
                "params": {"brightness": 0.3},
                "description": "test",
            },
        ],
        "quality_checks_enabled": True,
        "auto_balance_demographics": True,
    }
    put_resp = client.put(
        f"{API}/config/augmentation", headers=admin_headers, json=payload
    )
    assert put_resp.status_code == 200, put_resp.text
    updated = put_resp.json()

    # Verify PUT response reflects the submitted changes
    enabled_map = {t["technique"]: t["enabled"] for t in updated["techniques"]}
    assert enabled_map["cutmix"] is True
    assert enabled_map["mixup"] is True
    assert enabled_map["geometric"] is True
    assert enabled_map["adversarial"] is False
    assert updated["auto_balance_demographics"] is True

    # Verify that a fresh GET returns the persisted values
    refetched = client.get(f"{API}/config/augmentation", headers=admin_headers).json()
    refetched_map = {t["technique"]: t["enabled"] for t in refetched["techniques"]}
    assert refetched_map["cutmix"] is True
    assert refetched_map["mixup"] is True
    assert refetched_map["geometric"] is True

    # Make sure we didn't just mirror the pre-existing state
    assert updated != original or original["auto_balance_demographics"] is True


# ── ENH-003 Model Architecture Config GET + PUT ─────────────────────────────


def test_enh_003_model_architecture_config_get(client, admin_headers):
    resp = client.get(f"{API}/config/model-architecture", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["current_architecture"]
    for key in ("vit_config", "hybrid_config", "ensemble_config"):
        assert key in body and isinstance(body[key], dict)

    assert "resnet100" in body["available_backbones"]
    assert "vit_base" in body["available_vit_variants"]
    assert "bagging" in body["available_ensemble_methods"]


def test_enh_003_model_architecture_config_put_persists(client, admin_headers):
    payload = {
        "vit_enabled": True,
        "vit_variant": "vit_large",
        "hybrid_cnn_transformer": True,
        "cnn_backbone": "resnet152",
        "ensemble_enabled": True,
        "ensemble_methods": ["bagging", "stacking"],
    }
    put_resp = client.put(
        f"{API}/config/model-architecture", headers=admin_headers, json=payload
    )
    assert put_resp.status_code == 200, put_resp.text
    updated = put_resp.json()
    assert updated["vit_config"]["enabled"] is True
    assert updated["vit_config"]["variant"] == "vit_large"
    assert updated["hybrid_config"]["enabled"] is True
    assert updated["hybrid_config"]["cnn_backbone"] == "resnet152"
    assert updated["ensemble_config"]["enabled"] is True
    assert set(updated["ensemble_config"]["methods"]) == {"bagging", "stacking"}

    refetched = client.get(
        f"{API}/config/model-architecture", headers=admin_headers
    ).json()
    assert refetched["vit_config"]["variant"] == "vit_large"
    assert refetched["ensemble_config"]["enabled"] is True


# ── ENH-004 Current Capabilities ────────────────────────────────────────────


def test_enh_004_current_capabilities(client, admin_headers):
    resp = client.get(f"{API}/capabilities/current", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "implemented_features" in body
    assert len(body["implemented_features"]) >= 5
    first_feature = body["implemented_features"][0]
    assert "feature" in first_feature
    assert "technology" in first_feature
    assert "status" in first_feature

    assert "current_limitations" in body
    assert "phase_summary" in body
    assert len(body["phase_summary"]) == 4
    phase_names = {p["phase"] for p in body["phase_summary"]}
    assert phase_names == {"Phase 1", "Phase 2", "Phase 3", "Phase 4"}

    assert body["system_version"]


# ── ENH-005 Priority Matrix ─────────────────────────────────────────────────


def test_enh_005_priority_matrix(client, admin_headers):
    resp = client.get(f"{API}/priority-matrix", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "high_priority" in body
    assert "medium_priority" in body
    assert "low_priority" in body
    assert body["total_items"] == (
        len(body["high_priority"]) + len(body["medium_priority"]) + len(body["low_priority"])
    )
    assert body["total_items"] > 0

    first = body["high_priority"][0]
    for key in ("enhancement", "impact", "effort", "roi", "priority_tier", "category"):
        assert key in first


# ── ENH-006 Metrics Targets ─────────────────────────────────────────────────


def test_enh_006_metrics_targets(client, admin_headers):
    resp = client.get(f"{API}/metrics/targets", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    for bucket in ("accuracy_metrics", "system_metrics", "business_metrics"):
        assert bucket in body and len(body[bucket]) >= 1
        sample = body[bucket][0]
        assert "metric" in sample
        assert "current" in sample
        assert "target" in sample


# ── ENH-007 Bias Audit ──────────────────────────────────────────────────────


def test_enh_007_bias_audit(client, admin_headers):
    resp = client.get(f"{API}/audit/bias", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "overall_fairness_score" in body
    assert isinstance(body["overall_fairness_score"], (int, float))

    assert "demographic_parity" in body
    assert "status" in body["demographic_parity"]
    assert "equal_opportunity" in body
    assert "status" in body["equal_opportunity"]

    assert isinstance(body["recommendations"], list)
    assert body["audited_at"]


def test_enh_007_bias_audit_history_endpoint(client, admin_headers):
    # Trigger an audit run so the history table has at least one record
    client.get(f"{API}/audit/bias", headers=admin_headers)
    resp = client.get(f"{API}/audit/bias/history", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 1


# ── ENH-008 Rate Limits CRUD ────────────────────────────────────────────────


def test_enh_008_rate_limits_full_crud_cycle(client, admin_headers):
    # 1. List — should start empty (or existing values; we only check structure)
    list_resp = client.get(f"{API}/rate-limits/", headers=admin_headers)
    assert list_resp.status_code == 200, list_resp.text
    starting = list_resp.json()
    assert isinstance(starting, list)

    # 2. Create a new rule
    payload = {
        "endpoint_pattern": "/api/v1/cameras/*",
        "max_requests": 500,
        "window_seconds": 60,
        "is_active": True,
        "priority": 10,
        "description": "Acceptance test rule",
    }
    create_resp = client.post(
        f"{API}/rate-limits/", headers=admin_headers, json=payload
    )
    assert create_resp.status_code == 200, create_resp.text
    created = create_resp.json()
    assert created["endpoint_pattern"] == "/api/v1/cameras/*"
    assert created["max_requests"] == 500
    rule_id = created["id"]

    # 3. Make sure it shows up in the list
    list_after = client.get(f"{API}/rate-limits/", headers=admin_headers).json()
    assert any(r["id"] == rule_id for r in list_after)
    assert len(list_after) == len(starting) + 1

    # 4. Update the rule
    update_payload = {"max_requests": 750, "is_active": False}
    update_resp = client.put(
        f"{API}/rate-limits/{rule_id}",
        headers=admin_headers,
        json=update_payload,
    )
    assert update_resp.status_code == 200, update_resp.text
    updated = update_resp.json()
    assert updated["max_requests"] == 750
    assert updated["is_active"] is False

    # 5. Summary endpoint should count rules correctly
    summary_resp = client.get(f"{API}/rate-limits/summary", headers=admin_headers)
    assert summary_resp.status_code == 200, summary_resp.text
    summary = summary_resp.json()
    assert summary["total_rules"] >= 1

    # 6. Delete the rule
    delete_resp = client.delete(
        f"{API}/rate-limits/{rule_id}", headers=admin_headers
    )
    assert delete_resp.status_code == 200, delete_resp.text

    # 7. Confirm it's gone
    list_final = client.get(f"{API}/rate-limits/", headers=admin_headers).json()
    assert not any(r["id"] == rule_id for r in list_final)


def test_enh_008_rate_limit_requires_admin(client, staff_headers):
    payload = {
        "endpoint_pattern": "/api/v1/test",
        "max_requests": 100,
        "window_seconds": 60,
        "is_active": True,
    }
    resp = client.post(f"{API}/rate-limits/", headers=staff_headers, json=payload)
    assert resp.status_code == 403


# ── ENH-013 Differential Privacy Config (US-FUT-013) ────────────────────────


def test_enh_013_differential_privacy_get_returns_defaults(client, admin_headers):
    resp = client.get(f"{API}/config/differential-privacy", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    for key in (
        "enabled",
        "mechanism",
        "epsilon",
        "delta",
        "noise_multiplier",
        "clip_norm",
        "protected_fields",
        "available_mechanisms",
        "privacy_budget_summary",
    ):
        assert key in body, f"missing key: {key}"

    assert body["mechanism"] in ("gaussian", "laplace")
    assert body["available_mechanisms"] == ["gaussian", "laplace"]
    assert isinstance(body["protected_fields"], list)
    assert body["privacy_budget_summary"]["epsilon"] == body["epsilon"]


def test_enh_013_differential_privacy_put_persists(client, admin_headers):
    payload = {
        "enabled": True,
        "mechanism": "laplace",
        "epsilon": 2.5,
        "delta": 1e-6,
        "noise_multiplier": 1.3,
        "clip_norm": 1.5,
        "protected_fields": ["face_embedding", "visitor_email"],
    }
    put_resp = client.put(
        f"{API}/config/differential-privacy", headers=admin_headers, json=payload
    )
    assert put_resp.status_code == 200, put_resp.text
    updated = put_resp.json()
    assert updated["enabled"] is True
    assert updated["mechanism"] == "laplace"
    assert updated["epsilon"] == 2.5
    assert "visitor_email" in updated["protected_fields"]

    refetched = client.get(
        f"{API}/config/differential-privacy", headers=admin_headers
    ).json()
    assert refetched["enabled"] is True
    assert refetched["mechanism"] == "laplace"
    assert refetched["epsilon"] == 2.5


def test_enh_013_differential_privacy_put_requires_admin(client, staff_headers):
    resp = client.put(
        f"{API}/config/differential-privacy",
        headers=staff_headers,
        json={"enabled": True, "epsilon": 1.0},
    )
    assert resp.status_code == 403


# ── ENH-029 Data Minimization Config (US-FUT-029) ───────────────────────────


def test_enh_029_data_minimization_get_returns_defaults(client, admin_headers):
    resp = client.get(f"{API}/config/data-minimization", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    for key in (
        "retain_fields",
        "drop_fields",
        "retention_days",
        "secure_computation_enabled",
        "anonymize_on_export",
        "aggregation_only",
        "available_fields",
        "summary",
    ):
        assert key in body, f"missing key: {key}"

    assert isinstance(body["available_fields"], list)
    assert "face_embedding" in body["available_fields"]
    assert "raw_face_image" in body["available_fields"]
    assert "minimization_ratio" in body["summary"]


def test_enh_029_data_minimization_put_persists(client, admin_headers):
    payload = {
        "retain_fields": ["face_embedding", "behavior_score"],
        "drop_fields": ["raw_face_image", "audio_embedding"],
        "retention_days": 30,
        "secure_computation_enabled": True,
        "anonymize_on_export": True,
        "aggregation_only": False,
    }
    put_resp = client.put(
        f"{API}/config/data-minimization", headers=admin_headers, json=payload
    )
    assert put_resp.status_code == 200, put_resp.text
    updated = put_resp.json()
    assert set(updated["retain_fields"]) == {"face_embedding", "behavior_score"}
    assert set(updated["drop_fields"]) == {"raw_face_image", "audio_embedding"}
    assert updated["retention_days"] == 30
    assert updated["secure_computation_enabled"] is True
    assert updated["summary"]["fields_retained_count"] == 2
    assert updated["summary"]["fields_dropped_count"] == 2

    refetched = client.get(
        f"{API}/config/data-minimization", headers=admin_headers
    ).json()
    assert refetched["retention_days"] == 30
    assert refetched["secure_computation_enabled"] is True


def test_enh_029_data_minimization_rejects_overlap(client, admin_headers):
    payload = {
        "retain_fields": ["face_embedding", "visitor_name"],
        "drop_fields": ["visitor_name"],  # overlap!
        "retention_days": 90,
    }
    resp = client.put(
        f"{API}/config/data-minimization", headers=admin_headers, json=payload
    )
    assert resp.status_code == 400
    assert "visitor_name" in resp.json()["detail"]


def test_enh_029_data_minimization_rejects_unknown_fields(client, admin_headers):
    payload = {
        "retain_fields": ["not_a_real_field"],
        "drop_fields": ["raw_face_image"],
        "retention_days": 90,
    }
    resp = client.put(
        f"{API}/config/data-minimization", headers=admin_headers, json=payload
    )
    assert resp.status_code == 400


def test_enh_029_data_minimization_put_requires_admin(client, staff_headers):
    resp = client.put(
        f"{API}/config/data-minimization",
        headers=staff_headers,
        json={"retain_fields": ["face_embedding"], "drop_fields": ["raw_face_image"]},
    )
    assert resp.status_code == 403


# ── ENH-039 Visitor Flow & Heatmap Analytics (US-FUT-039) ───────────────────


def test_enh_039_visitor_flow_analytics_structure(client, admin_headers):
    resp = client.get(
        f"{API}/analytics/visitor-flow?lookback_hours=24", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Top-level structure
    for key in (
        "lookback_hours",
        "since",
        "totals",
        "hourly_timeline",
        "camera_density",
        "peak_camera",
        "dwell_time",
        "heatmap",
        "generated_at",
    ):
        assert key in body, f"missing key: {key}"

    assert body["lookback_hours"] == 24

    # Totals
    totals = body["totals"]
    for key in ("total_events", "unique_visitors", "identified_events", "identified_rate"):
        assert key in totals

    # Timeline is a list (may be empty on a fresh DB)
    assert isinstance(body["hourly_timeline"], list)
    assert isinstance(body["camera_density"], list)

    # Dwell time
    dwell = body["dwell_time"]
    for key in ("median_seconds", "average_seconds", "sample_count"):
        assert key in dwell

    # Heatmap must be a 10x10 grid
    heatmap = body["heatmap"]
    assert heatmap["grid_size"] == [10, 10]
    assert len(heatmap["raw_grid"]) == 10
    assert all(len(row) == 10 for row in heatmap["raw_grid"])
    assert len(heatmap["normalized_grid"]) == 10
    assert all(len(row) == 10 for row in heatmap["normalized_grid"])
    assert "peak_cell_events" in heatmap


def test_enh_039_visitor_flow_respects_lookback_bounds(client, admin_headers):
    # Too low
    resp = client.get(
        f"{API}/analytics/visitor-flow?lookback_hours=0", headers=admin_headers
    )
    assert resp.status_code == 422

    # Too high
    resp = client.get(
        f"{API}/analytics/visitor-flow?lookback_hours=10000", headers=admin_headers
    )
    assert resp.status_code == 422


def test_enh_039_visitor_flow_camera_filter_accepted(client, admin_headers):
    # A non-existent camera id should simply return zero events, not error.
    resp = client.get(
        f"{API}/analytics/visitor-flow?lookback_hours=24"
        f"&camera_id=00000000-0000-0000-0000-000000000000",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["totals"]["total_events"] == 0


# ── Phase 2/3 upgraded story_ids must still respond correctly ───────────────


def test_phase_2_and_3_upgraded_enhancements_are_deployed(client, admin_headers):
    """After Phase 2/3 implementation, these stories should be status=deployed
    and enabled=True so the roadmap tab shows real progress."""
    resp = client.get(f"{API}/", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    by_story = {item["story_id"]: item for item in items}

    # The core Phase 2/3 items that ship real backend services
    expected_deployed = {
        "US-FUT-001",  # Multimodal
        "US-FUT-002",  # Edge Computing
        "US-FUT-003",  # Edge Model Opt
        "US-FUT-004",  # ViT
        "US-FUT-005",  # Ensemble
        "US-FUT-006",  # Self-Supervised
        "US-FUT-009",  # Synthetic Data
        "US-FUT-013",  # Differential Privacy (new)
        "US-FUT-016",  # Federated Learning
        "US-FUT-023",  # Hybrid CNN-Transformer
        "US-FUT-025",  # Multi-Angle Face
        "US-FUT-029",  # Data Minimization (new)
        "US-FUT-039",  # Visitor Flow (new)
    }
    # The list endpoint normalizes 'deployed' -> 'live' for UI display,
    # so assert on the normalized label here.
    for story_id in expected_deployed:
        assert story_id in by_story, f"missing seed row: {story_id}"
        assert by_story[story_id]["status"] == "live", (
            f"{story_id} should be 'live' (deployed) but was {by_story[story_id]['status']}"
        )
        assert by_story[story_id]["enabled"] is True, (
            f"{story_id} should be enabled=True"
        )


def test_roadmap_overview_reflects_phase_progress(client, admin_headers):
    resp = client.get(f"{API}/roadmap/overview", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total_enhancements"] > 0
    assert body["enabled_count"] > 0
    # Overall completion must now be above 0 since Phase 1/2/3 ship real work
    assert body["completion_percent"] > 0

    # future_ready phase must exist and be non-empty
    phases = {p["phase"]: p for p in body["phases"]}
    assert "future_ready" in phases
    assert len(phases["future_ready"]["enhancements"]) > 0
