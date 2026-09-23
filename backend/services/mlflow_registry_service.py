from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from core.paths import DATA_DIR, data_path
from core.runtime_registry import load_runtime_registry


def mlflow_registry_path() -> str:
    return data_path("mlflow_registry.json")


def _mlflow_available() -> bool:
    try:
        import mlflow  # noqa: F401
        return True
    except Exception:
        return False


def _default_registry_state() -> Dict[str, Any]:
    return {
        "status": "ok",
        "tracking_uri": os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"),
        "mlflow_available": _mlflow_available(),
        "last_updated_at": None,
        "models": [],
        "promotions": [],
    }


def load_mlflow_registry() -> Dict[str, Any]:
    state = _default_registry_state()
    path = mlflow_registry_path()
    if not os.path.exists(path):
        return state

    try:
        with open(path, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)
    except Exception:
        return state

    state["status"] = persisted.get("status", state["status"])
    state["tracking_uri"] = persisted.get("tracking_uri", state["tracking_uri"])
    state["mlflow_available"] = persisted.get("mlflow_available", state["mlflow_available"])
    state["last_updated_at"] = persisted.get("last_updated_at", state["last_updated_at"])
    state["models"] = persisted.get("models", state["models"])
    state["promotions"] = persisted.get("promotions", state["promotions"])
    return state


def save_mlflow_registry(state: Dict[str, Any]) -> Dict[str, Any]:
    state = dict(state)
    state["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    state["tracking_uri"] = os.getenv("MLFLOW_TRACKING_URI", state.get("tracking_uri") or "http://127.0.0.1:5000")
    state["mlflow_available"] = _mlflow_available()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(mlflow_registry_path(), "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
    return state


def _sync_models_with_runtime_registry(state: Dict[str, Any]) -> Dict[str, Any]:
    runtime_registry = load_runtime_registry()
    existing = {
        item.get("component"): dict(item)
        for item in state.get("models", [])
        if isinstance(item, dict) and item.get("component")
    }

    synced: List[Dict[str, Any]] = []
    for component in runtime_registry.get("components", []):
        component_name = component.get("component")
        if not component_name:
            continue

        current_model = component.get("current_model") or "unknown"
        existing_item = existing.get(component_name, {})
        previous_registered = existing_item.get("registered_model")
        last_transitioned_at = existing_item.get("last_transitioned_at")
        if previous_registered and previous_registered != current_model:
            last_transitioned_at = datetime.now(timezone.utc).isoformat()

        tags = dict(existing_item.get("tags", {}))
        tags.update(
            {
                "runtime": str(component.get("runtime", "unknown")),
                "status": str(component.get("status", "unknown")),
            }
        )

        stage = "Production" if str(component.get("status", "")).lower() in {"active", "pilot"} else "Staging"
        synced.append(
            {
                "component": component_name,
                "registered_model": current_model,
                "version": str(existing_item.get("version", "current")),
                "stage": stage,
                "run_id": existing_item.get("run_id"),
                "artifact_uri": component.get("current_artifact") or existing_item.get("artifact_uri"),
                "metrics": existing_item.get("metrics", {}),
                "tags": tags,
                "last_transitioned_at": last_transitioned_at,
            }
        )

    state["models"] = sorted(synced, key=lambda item: item.get("component", ""))
    return state


def get_registry_snapshot() -> Dict[str, Any]:
    state = load_mlflow_registry()
    state = _sync_models_with_runtime_registry(state)
    return save_mlflow_registry(state)


def list_promotions(limit: int = 20) -> List[Dict[str, Any]]:
    state = load_mlflow_registry()
    promotions = state.get("promotions", [])
    if not isinstance(promotions, list):
        return []
    return promotions[: max(1, min(limit, 200))]


def record_promotion(
    *,
    component: str,
    previous_model: str | None,
    previous_artifact: str | None,
    candidate_model: str,
    candidate_artifact: str | None,
    requested_by: str,
    benchmark_status: str,
    benchmark_production_ready: bool,
    benchmark_sample_size: int,
    reason: str | None,
    applied: bool,
    notes: str | None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    state = load_mlflow_registry()
    state = _sync_models_with_runtime_registry(state)

    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "promotion_id": str(uuid.uuid4()),
        "component": component,
        "previous_model": previous_model,
        "previous_artifact": previous_artifact,
        "candidate_model": candidate_model,
        "candidate_artifact": candidate_artifact,
        "requested_by": requested_by,
        "requested_at": now_iso,
        "benchmark_status": benchmark_status,
        "benchmark_production_ready": benchmark_production_ready,
        "benchmark_sample_size": benchmark_sample_size,
        "reason": reason,
        "applied": applied,
        "applied_at": now_iso if applied else None,
        "notes": notes,
    }

    promotions = state.get("promotions", [])
    if not isinstance(promotions, list):
        promotions = []
    state["promotions"] = [record] + promotions[:199]

    model_entry = next(
        (item for item in state.get("models", []) if item.get("component") == component),
        None,
    )
    if not model_entry:
        model_entry = {
            "component": component,
            "registered_model": previous_model or candidate_model,
            "version": "current",
            "stage": "Staging",
            "run_id": None,
            "artifact_uri": previous_artifact,
            "metrics": {},
            "tags": {},
            "last_transitioned_at": None,
        }
        state.setdefault("models", []).append(model_entry)

    tags = dict(model_entry.get("tags", {}))
    tags["last_promotion_id"] = record["promotion_id"]
    tags["last_promotion_status"] = "applied" if applied else "blocked"
    model_entry["tags"] = tags

    if applied:
        model_entry["registered_model"] = candidate_model
        model_entry["artifact_uri"] = candidate_artifact
        model_entry["version"] = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        model_entry["stage"] = "Production"
        model_entry["last_transitioned_at"] = now_iso
    else:
        model_entry["stage"] = "Staging"

    state = save_mlflow_registry(state)
    return state, record


def log_training_run(
    *,
    component: str,
    run_name: str,
    params: Dict[str, Any],
    metrics: Dict[str, float],
    tags: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    if not _mlflow_available():
        return {"status": "skipped", "reason": "mlflow_unavailable"}

    try:
        import mlflow
        mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
        with mlflow.start_run(run_name=run_name) as run:
            if params:
                mlflow.log_params(params)
            if metrics:
                mlflow.log_metrics(metrics)
            if tags:
                mlflow.set_tags(tags)
        run_id = run.info.run_id
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}

    state = load_mlflow_registry()
    state = _sync_models_with_runtime_registry(state)
    model_entry = next(
        (item for item in state.get("models", []) if item.get("component") == component),
        None,
    )
    if not model_entry:
        model_entry = {
            "component": component,
            "registered_model": component,
            "version": "current",
            "stage": "Staging",
            "run_id": run_id,
            "artifact_uri": None,
            "metrics": {},
            "tags": {},
            "last_transitioned_at": None,
        }
        state.setdefault("models", []).append(model_entry)

    model_entry["run_id"] = run_id
    model_entry["metrics"] = {**model_entry.get("metrics", {}), **metrics}
    if tags:
        model_entry["tags"] = {**model_entry.get("tags", {}), **tags}

    state = save_mlflow_registry(state)
    return {
        "status": "logged",
        "run_id": run_id,
        "tracking_uri": state.get("tracking_uri"),
    }


def promotion_health_summary() -> Dict[str, Any]:
    state = load_mlflow_registry()
    promotions = state.get("promotions", [])
    if not isinstance(promotions, list):
        promotions = []
    applied = sum(1 for item in promotions if item.get("applied"))
    blocked = sum(1 for item in promotions if not item.get("applied"))
    last = promotions[0] if promotions else None
    return {
        "total_promotions": len(promotions),
        "applied_promotions": applied,
        "blocked_promotions": blocked,
        "last_promotion_at": last.get("requested_at") if last else None,
    }
