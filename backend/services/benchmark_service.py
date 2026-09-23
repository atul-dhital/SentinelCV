import json
import os
from datetime import datetime
from typing import Any, Dict, List

from core.runtime_registry import benchmark_history_path, benchmark_results_path
from scripts.benchmark_accuracy import run_benchmark


TARGET_BASELINE_ACCURACY = 95.0
TARGET_LATENCY_MS = 150.0
TARGET_MRR = 0.95
TARGET_MULTI_ANGLE_BOOST_PCT = 2.0
HISTORY_LIMIT = 12


def _empty_summary() -> Dict[str, Any]:
    return {
        "status": "not_run",
        "sample_size": 0,
        "run_at": None,
        "baseline_accuracy": None,
        "multi_angle_accuracy": None,
        "multi_angle_boost_pct": None,
        "mean_reciprocal_rank": None,
        "avg_latency_ms": None,
        "latency_target_met": False,
        "production_ready": False,
        "target_baseline_accuracy": TARGET_BASELINE_ACCURACY,
        "target_latency_ms": TARGET_LATENCY_MS,
        "accuracy_gap_pct": None,
        "latency_budget_remaining_ms": None,
        "recommendation": "Run the baseline benchmark suite to populate this summary.",
        "results_path": benchmark_results_path(),
        "gate_metrics": [],
        "history": [],
    }


def _read_json(path: str, fallback: Any) -> Any:
    if not os.path.exists(path):
        return fallback

    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return fallback


def _write_json(path: str, payload: Any) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _parse_datetime(raw_value: Any) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _build_gate_metrics(
    baseline_accuracy: float | None,
    avg_latency_ms: float | None,
    mean_reciprocal_rank: float | None,
    multi_angle_boost_pct: float | None,
) -> List[Dict[str, Any]]:
    def gate(name: str, current: float | None, target: float, unit: str, pass_when_high: bool, detail: str) -> Dict[str, Any]:
        passed = False
        if current is not None:
            passed = current >= target if pass_when_high else current <= target
        return {
            "name": name,
            "status": "pass" if passed else "fail",
            "current_value": current,
            "target_value": target,
            "unit": unit,
            "detail": detail,
        }

    return [
        gate(
            "Baseline accuracy",
            baseline_accuracy,
            TARGET_BASELINE_ACCURACY,
            "%",
            True,
            "Measures single-frame identification accuracy against the deployment gate.",
        ),
        gate(
            "Average latency",
            avg_latency_ms,
            TARGET_LATENCY_MS,
            "ms",
            False,
            "Keeps the baseline matcher within the live latency budget.",
        ),
        gate(
            "Ranking quality",
            mean_reciprocal_rank,
            TARGET_MRR,
            "score",
            True,
            "Tracks whether the correct identity stays at the top of the ranked results.",
        ),
        gate(
            "Multi-angle lift",
            multi_angle_boost_pct,
            TARGET_MULTI_ANGLE_BOOST_PCT,
            "%",
            True,
            "Confirms that burst consensus meaningfully improves over single-frame matching.",
        ),
    ]


def _history_entry_from_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "run_at": summary.get("run_at").isoformat() if isinstance(summary.get("run_at"), datetime) else summary.get("run_at"),
        "sample_size": summary.get("sample_size", 0),
        "status": summary.get("status", "unknown"),
        "baseline_accuracy": summary.get("baseline_accuracy"),
        "multi_angle_accuracy": summary.get("multi_angle_accuracy"),
        "avg_latency_ms": summary.get("avg_latency_ms"),
        "production_ready": bool(summary.get("production_ready", False)),
        "latency_target_met": bool(summary.get("latency_target_met", False)),
    }


def load_benchmark_history() -> List[Dict[str, Any]]:
    raw_history = _read_json(benchmark_history_path(), [])
    if not isinstance(raw_history, list):
        return []

    history: List[Dict[str, Any]] = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        history.append(
            {
                "run_at": _parse_datetime(item.get("run_at")),
                "sample_size": item.get("sample_size", 0),
                "status": item.get("status", "unknown"),
                "baseline_accuracy": item.get("baseline_accuracy"),
                "multi_angle_accuracy": item.get("multi_angle_accuracy"),
                "avg_latency_ms": item.get("avg_latency_ms"),
                "production_ready": bool(item.get("production_ready", False)),
                "latency_target_met": bool(item.get("latency_target_met", False)),
            }
        )

    history.sort(key=lambda item: item.get("run_at") or datetime.min)
    return history[-HISTORY_LIMIT:]


def _build_summary_from_payload(payload: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
    baseline = payload.get("baseline", {})
    multi_angle = payload.get("multi_angle", {})
    summary = payload.get("summary", {})

    baseline_accuracy = _round_or_none(baseline.get("accuracy"))
    multi_angle_accuracy = _round_or_none(multi_angle.get("accuracy"))
    multi_angle_boost_pct = _round_or_none(multi_angle.get("accuracy_boost_pct"))
    avg_latency_ms = _round_or_none(baseline.get("avg_latency_ms"))
    mean_reciprocal_rank = _round_or_none(baseline.get("mrr"), 4)

    accuracy_gap_pct = None
    if baseline_accuracy is not None:
        accuracy_gap_pct = round(max(0.0, TARGET_BASELINE_ACCURACY - baseline_accuracy), 2)

    latency_budget_remaining_ms = None
    if avg_latency_ms is not None:
        latency_budget_remaining_ms = round(TARGET_LATENCY_MS - avg_latency_ms, 2)

    return {
        "status": "completed",
        "sample_size": payload.get("sample_size", 0),
        "run_at": _parse_datetime(payload.get("timestamp")),
        "baseline_accuracy": baseline_accuracy,
        "multi_angle_accuracy": multi_angle_accuracy,
        "multi_angle_boost_pct": multi_angle_boost_pct,
        "mean_reciprocal_rank": mean_reciprocal_rank,
        "avg_latency_ms": avg_latency_ms,
        "latency_target_met": bool(summary.get("latency_target_met", False)),
        "production_ready": bool(summary.get("is_ready_for_prod", False)),
        "target_baseline_accuracy": TARGET_BASELINE_ACCURACY,
        "target_latency_ms": TARGET_LATENCY_MS,
        "accuracy_gap_pct": accuracy_gap_pct,
        "latency_budget_remaining_ms": latency_budget_remaining_ms,
        "recommendation": summary.get("recommendation"),
        "results_path": benchmark_results_path(),
        "gate_metrics": _build_gate_metrics(
            baseline_accuracy=baseline_accuracy,
            avg_latency_ms=avg_latency_ms,
            mean_reciprocal_rank=mean_reciprocal_rank,
            multi_angle_boost_pct=multi_angle_boost_pct,
        ),
        "history": history,
    }


def _persist_history(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    history = load_benchmark_history()
    history.append(_history_entry_from_summary(summary))
    history = history[-HISTORY_LIMIT:]
    serializable_history = [
        {
            **item,
            "run_at": item.get("run_at").isoformat() if isinstance(item.get("run_at"), datetime) else item.get("run_at"),
        }
        for item in history
    ]
    _write_json(benchmark_history_path(), serializable_history)
    return load_benchmark_history()


def _failed_summary(error: Exception) -> Dict[str, Any]:
    summary = _empty_summary()
    summary["status"] = "failed"
    error_text = str(error)
    if "readonly database" in error_text.lower():
        summary["recommendation"] = (
            "Benchmark run failed because the current database is read-only. "
            "Re-run with a writable DATABASE_URL or through the Docker stack."
        )
    else:
        summary["recommendation"] = f"Benchmark run failed: {error.__class__.__name__}"
    summary["history"] = load_benchmark_history()
    return summary


def load_benchmark_summary() -> Dict[str, Any]:
    path = benchmark_results_path()
    history = load_benchmark_history()
    payload = _read_json(path, None)
    if not isinstance(payload, dict):
        summary = _empty_summary()
        summary["history"] = history
        return summary
    return _build_summary_from_payload(payload, history)


def run_baseline_benchmark(sample_size: int = 30) -> Dict[str, Any]:
    bounded_sample_size = max(10, min(sample_size, 200))
    try:
        payload = run_benchmark(
            sample_size=bounded_sample_size,
            output_path=benchmark_results_path(),
        )
    except Exception as error:
        return _failed_summary(error)

    summary = _build_summary_from_payload(payload, load_benchmark_history())
    summary["history"] = _persist_history(summary)
    return summary
