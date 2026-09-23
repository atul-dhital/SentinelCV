from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from core.paths import DATA_DIR, data_path


logger = logging.getLogger(__name__)

ARTIFACT_SUBDIR = "model_artifacts"
LATEST_ARTIFACT_NAME = "latest_custom_classifier.pt"

_CACHE_LOCK = threading.Lock()
_BUNDLE_CACHE: Dict[str, Dict[str, Any]] = {}


class SimpleClassifier(nn.Module):
    """Inference-time mirror of ai_services/training_system.py:SimpleClassifier."""

    def __init__(self, input_dim: int, num_classes: int, hidden_dims: Optional[list[int]] = None, dropout: float = 0.3):
        super().__init__()
        hidden_dims = hidden_dims or [256, 128, 64]
        layers: list[nn.Module] = []
        prev = input_dim
        for i, h in enumerate(hidden_dims):
            layers.append(nn.Linear(prev, h))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(p=dropout * 0.67 if i == len(hidden_dims) - 1 else dropout))
            prev = h
        layers.append(nn.Linear(prev, num_classes))
        self.network = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)


class _ArcFaceInferenceModel(nn.Module):
    """Inference wrapper for a trained ArcFaceModel — returns scaled cosine logits (no margin).
    Matches ArcFaceModel architecture in ai_services/training_system.py."""

    def __init__(self, input_dim: int, num_classes: int, scale: float = 64.0):
        super().__init__()
        self.scale = scale
        self.feature_extractor = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
        )
        self.weight = nn.Parameter(torch.FloatTensor(num_classes, 128))
        nn.init.xavier_uniform_(self.weight)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = F.normalize(self.feature_extractor(x), dim=1)
        W = F.normalize(self.weight, dim=1)
        cos = torch.clamp(F.linear(features, W), -1 + 1e-7, 1 - 1e-7)
        return cos * self.scale  # logits; softmax applied downstream


class _EnsembleClassifier:
    """Wraps multiple loaded model bundles for weighted-average ensemble inference."""

    def __init__(self, bundles: List[Dict[str, Any]], weights: List[float]):
        self.bundles = bundles
        self.weights = weights

    def predict_proba(self, normalized_tensor: torch.Tensor) -> np.ndarray:
        total = np.zeros(len(self.bundles[0]["class_to_visitor_id"]), dtype=np.float32)
        for bundle, w in zip(self.bundles, self.weights):
            with torch.no_grad():
                logits = bundle["model"](normalized_tensor)
                probs = torch.softmax(logits, dim=1).cpu().numpy()[0]
            if probs.shape[0] == total.shape[0]:
                total += w * probs
        return total


def _artifact_dir(organization_id: str) -> Path:
    return Path(DATA_DIR) / ARTIFACT_SUBDIR / str(organization_id)


def _relative_to_data(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(DATA_DIR).resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def resolve_artifact_path(artifact_path: str) -> Path:
    candidate = Path(artifact_path)
    if candidate.is_absolute():
        return candidate.resolve()
    return Path(data_path(artifact_path)).resolve()


def artifact_exists(artifact_path: str) -> bool:
    return resolve_artifact_path(artifact_path).exists()


def save_training_artifact(
    *,
    organization_id: str,
    job_id: str,
    model_state_dict: Dict[str, Any],
    input_dim: int,
    num_classes: int,
    class_to_visitor_id: Dict[str, str],
    scaler_mean: Iterable[float],
    scaler_scale: Iterable[float],
    config: Dict[str, Any],
    metrics: Dict[str, float],
    hidden_dims: Optional[list[int]] = None,
    dropout: float = 0.3,
    architecture: str = "simple",
) -> Dict[str, str]:
    """Persist a trained classifier bundle so it can be activated at runtime."""
    artifact_dir = _artifact_dir(organization_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    bundle = {
        "format_version": 3,
        "architecture": architecture,
        "organization_id": str(organization_id),
        "job_id": str(job_id),
        "input_dim": int(input_dim),
        "num_classes": int(num_classes),
        "hidden_dims": hidden_dims or [256, 128, 64],
        "dropout": float(dropout),
        "class_to_visitor_id": {str(key): str(value) for key, value in class_to_visitor_id.items()},
        "scaler_mean": [float(value) for value in scaler_mean],
        "scaler_scale": [float(value) for value in scaler_scale],
        "config": config,
        "metrics": metrics,
        "model_state_dict": model_state_dict,
    }

    artifact_path = artifact_dir / f"custom_classifier_{job_id}.pt"
    latest_path = artifact_dir / LATEST_ARTIFACT_NAME
    torch.save(bundle, artifact_path)
    torch.save(bundle, latest_path)

    with _CACHE_LOCK:
        _BUNDLE_CACHE.pop(str(artifact_path.resolve()), None)
        _BUNDLE_CACHE.pop(str(latest_path.resolve()), None)

    return {
        "artifact_path": _relative_to_data(artifact_path),
        "latest_artifact_path": _relative_to_data(latest_path),
    }


def save_ensemble_artifact(
    *,
    organization_id: str,
    ensemble_id: str,
    sub_artifacts: List[Dict[str, str]],
    weights: List[float],
    class_to_visitor_id: Dict[str, str],
    num_classes: int,
    input_dim: int,
    metrics: Dict[str, float],
) -> Dict[str, str]:
    """Persist an ensemble meta-artifact referencing N sub-model artifacts."""
    artifact_dir = _artifact_dir(organization_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    bundle = {
        "format_version": 3,
        "architecture": "ensemble",
        "organization_id": str(organization_id),
        "ensemble_id": str(ensemble_id),
        "sub_artifacts": sub_artifacts,
        "weights": [float(w) for w in weights],
        "class_to_visitor_id": {str(k): str(v) for k, v in class_to_visitor_id.items()},
        "num_classes": int(num_classes),
        "input_dim": int(input_dim),
        "metrics": metrics,
    }

    artifact_path = artifact_dir / f"ensemble_{ensemble_id}.pt"
    latest_path = artifact_dir / "latest_ensemble.pt"
    torch.save(bundle, artifact_path)
    torch.save(bundle, latest_path)

    with _CACHE_LOCK:
        _BUNDLE_CACHE.pop(str(artifact_path.resolve()), None)
        _BUNDLE_CACHE.pop(str(latest_path.resolve()), None)

    return {
        "artifact_path": _relative_to_data(artifact_path),
        "latest_artifact_path": _relative_to_data(latest_path),
    }


def _normalize_bundle(bundle: Dict[str, Any], resolved_path: Path) -> Dict[str, Any]:
    architecture = str(bundle.get("architecture") or "simple").lower()
    input_dim = int(bundle.get("input_dim") or 512)
    mapping = bundle.get("class_to_visitor_id") or {}
    num_classes = int(bundle.get("num_classes") or len(mapping))

    prepared = dict(bundle)
    prepared["resolved_path"] = str(resolved_path)
    prepared["input_dim"] = input_dim
    prepared["num_classes"] = num_classes
    prepared["class_to_visitor_id"] = {str(k): str(v) for k, v in mapping.items()}

    if architecture == "ensemble":
        # Load each sub-model bundle and wrap in _EnsembleClassifier
        sub_artifacts = bundle.get("sub_artifacts") or []
        weights = bundle.get("weights") or [1.0 / max(len(sub_artifacts), 1)] * len(sub_artifacts)
        sub_bundles = []
        for sa in sub_artifacts:
            sub_path = sa.get("artifact_path") or sa.get("path") or ""
            try:
                sub_bundle = load_artifact_bundle(sub_path)
                sub_bundles.append(sub_bundle)
            except Exception as exc:
                logger.warning("Ensemble: failed to load sub-artifact %s: %s", sub_path, exc)
        if not sub_bundles:
            raise ValueError("Ensemble artifact has no loadable sub-models")
        prepared["ensemble"] = _EnsembleClassifier(sub_bundles, weights)
        prepared["model"] = None  # not used directly for ensemble
        scaler_mean = np.zeros(input_dim, dtype=np.float32)
        scaler_scale = np.ones(input_dim, dtype=np.float32)

    elif architecture == "arcface":
        scale = float((bundle.get("config") or {}).get("scale") or 64.0)
        model = _ArcFaceInferenceModel(input_dim=input_dim, num_classes=num_classes, scale=scale)
        model.load_state_dict(bundle["model_state_dict"])
        model.eval()
        prepared["model"] = model
        prepared["ensemble"] = None
        scaler_mean = np.asarray(bundle.get("scaler_mean") or np.zeros(input_dim), dtype=np.float32)
        scaler_scale = np.asarray(bundle.get("scaler_scale") or np.ones(input_dim), dtype=np.float32)

    else:  # simple (default)
        hidden_dims = bundle.get("hidden_dims") or [256, 128, 64]
        dropout = float(bundle.get("dropout") or 0.3)
        model = SimpleClassifier(
            input_dim=input_dim,
            num_classes=num_classes,
            hidden_dims=[int(v) for v in hidden_dims],
            dropout=dropout,
        )
        model.load_state_dict(bundle["model_state_dict"])
        model.eval()
        prepared["model"] = model
        prepared["ensemble"] = None
        prepared["hidden_dims"] = [int(v) for v in hidden_dims]
        scaler_mean = np.asarray(bundle.get("scaler_mean") or np.zeros(input_dim), dtype=np.float32)
        scaler_scale = np.asarray(bundle.get("scaler_scale") or np.ones(input_dim), dtype=np.float32)

    scaler_scale = np.where(scaler_scale == 0, 1.0, scaler_scale)
    prepared["scaler_mean"] = scaler_mean
    prepared["scaler_scale"] = scaler_scale
    return prepared


def load_artifact_bundle(artifact_path: str) -> Dict[str, Any]:
    resolved_path = resolve_artifact_path(artifact_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"Custom classifier artifact not found: {resolved_path}")

    cache_key = str(resolved_path)
    mtime_ns = resolved_path.stat().st_mtime_ns

    with _CACHE_LOCK:
        cached = _BUNDLE_CACHE.get(cache_key)
        if cached and cached.get("mtime_ns") == mtime_ns:
            return cached["bundle"]

    bundle = torch.load(resolved_path, map_location="cpu", weights_only=True)
    prepared_bundle = _normalize_bundle(bundle, resolved_path)

    with _CACHE_LOCK:
        _BUNDLE_CACHE[cache_key] = {
            "mtime_ns": mtime_ns,
            "bundle": prepared_bundle,
        }

    return prepared_bundle


def predict_probabilities(
    artifact_path: str,
    embedding: Iterable[float],
    *,
    organization_id: Optional[str] = None,
) -> Dict[str, float]:
    """Return {visitor_id: probability} for a single embedding. Supports simple, arcface, ensemble."""
    bundle = load_artifact_bundle(artifact_path)

    bundle_org = bundle.get("organization_id")
    if organization_id and bundle_org and str(bundle_org) != str(organization_id):
        logger.warning(
            "Skipping custom classifier: org mismatch bundle=%s request=%s",
            bundle_org, organization_id,
        )
        return {}

    vector = np.asarray(list(embedding), dtype=np.float32)
    if not np.all(np.isfinite(vector)):
        logger.warning("predict_probabilities: embedding contains NaN/Inf — skipping")
        return {}

    input_dim = int(bundle["input_dim"])
    if vector.size > input_dim:
        vector = vector[:input_dim]
    elif vector.size < input_dim:
        vector = np.pad(vector, (0, input_dim - vector.size))

    normalized = (vector - bundle["scaler_mean"]) / bundle["scaler_scale"]
    tensor = torch.from_numpy(normalized.reshape(1, -1))
    mapping = bundle["class_to_visitor_id"]

    architecture = str(bundle.get("architecture") or "simple").lower()

    if architecture == "ensemble":
        ensemble: _EnsembleClassifier = bundle["ensemble"]
        probabilities = ensemble.predict_proba(tensor)
    else:
        with torch.no_grad():
            logits = bundle["model"](tensor)
            probabilities = torch.softmax(logits, dim=1).cpu().numpy()[0]

    results: Dict[str, float] = {}
    for index, probability in enumerate(probabilities):
        visitor_id = mapping.get(str(index))
        if visitor_id:
            results[str(visitor_id)] = float(probability)
    return results


def get_classifier_info(artifact_path: str) -> Dict[str, Any]:
    """Return metadata about a loaded classifier (for staleness checks)."""
    bundle = load_artifact_bundle(artifact_path)
    return {
        "architecture": bundle.get("architecture", "simple"),
        "num_classes": bundle.get("num_classes", 0),
        "class_to_visitor_id": bundle.get("class_to_visitor_id", {}),
        "metrics": bundle.get("metrics", {}),
        "organization_id": bundle.get("organization_id"),
    }

