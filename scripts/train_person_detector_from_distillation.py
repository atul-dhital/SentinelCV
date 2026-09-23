"""Train/promote a SentinelCV person detector from captured fusion hard frames.

This does not merge YOLO and RF-DETR weights directly. It uses the hard-frame
dataset captured by fallback_fusion as YOLO-format pseudo-labels, then fine-tunes
an Ultralytics detector into a single deployable artifact.

Examples:
    python scripts/train_person_detector_from_distillation.py --dry-run
    python scripts/train_person_detector_from_distillation.py --epochs 25 --promote
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time
from typing import Any, Dict, List, Sequence, Tuple

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("DATA_DIR", str(REPO_ROOT / "backend" / "data")))
DEFAULT_DATASET_DIR = DATA_DIR / "person_detector_distillation"
DEFAULT_ARTIFACT_DIR = DATA_DIR / "model_artifacts" / "person_detector"
DEFAULT_BENCHMARK_DIR = DATA_DIR / "benchmarks"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _find_pairs(dataset_dir: Path) -> List[Tuple[Path, Path]]:
    images_dir = dataset_dir / "images"
    labels_dir = dataset_dir / "labels"
    pairs: List[Tuple[Path, Path]] = []
    if not images_dir.exists() or not labels_dir.exists():
        return pairs

    for image_path in sorted(images_dir.iterdir()):
        if image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        label_path = labels_dir / f"{image_path.stem}.txt"
        if label_path.exists() and label_path.read_text(encoding="utf-8").strip():
            pairs.append((image_path, label_path))
    return pairs


def _copy_split(
    pairs: Sequence[Tuple[Path, Path]],
    split_dir: Path,
    val_ratio: float,
    seed: int,
) -> Dict[str, Any]:
    if split_dir.exists():
        shutil.rmtree(split_dir)

    rng = random.Random(seed)
    shuffled = list(pairs)
    rng.shuffle(shuffled)
    if len(shuffled) <= 1:
        val_count = 1 if shuffled else 0
    else:
        val_count = max(1, int(round(len(shuffled) * val_ratio)))
        val_count = min(val_count, len(shuffled) - 1)

    val_pairs = shuffled[:val_count]
    train_pairs = shuffled[val_count:] or shuffled

    for split_name, split_pairs in (("train", train_pairs), ("val", val_pairs or train_pairs)):
        image_out = split_dir / "images" / split_name
        label_out = split_dir / "labels" / split_name
        image_out.mkdir(parents=True, exist_ok=True)
        label_out.mkdir(parents=True, exist_ok=True)
        for image_path, label_path in split_pairs:
            shutil.copy2(image_path, image_out / image_path.name)
            shutil.copy2(label_path, label_out / label_path.name)

    data_yaml = split_dir / "data.yaml"
    data_yaml.write_text(
        "\n".join([
            f"path: {split_dir.as_posix()}",
            "train: images/train",
            "val: images/val",
            "names:",
            "  0: person",
            "",
        ]),
        encoding="utf-8",
    )

    return {
        "split_dir": str(split_dir),
        "data_yaml": str(data_yaml),
        "train_images": len(train_pairs),
        "val_images": len(val_pairs or train_pairs),
    }


def _resolve_base_model(base_model: str) -> Path:
    candidates = [
        Path(base_model),
        REPO_ROOT / base_model,
        REPO_ROOT / "models" / Path(base_model).name,
        DATA_DIR / base_model,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Base detector artifact not found: {base_model}")


def _copy_artifact(best_path: Path, artifact_dir: Path, model_name: str) -> Dict[str, str]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    artifact_path = artifact_dir / f"{model_name}_{stamp}.pt"
    shutil.copy2(best_path, artifact_path)
    latest_path = artifact_dir / "latest_person_detector.pt"
    shutil.copy2(best_path, latest_path)
    try:
        registry_artifact = str(latest_path.relative_to(DATA_DIR).as_posix())
    except ValueError:
        registry_artifact = str(latest_path.resolve())
    return {
        "artifact_path": str(artifact_path),
        "latest_path": str(latest_path),
        "registry_artifact": registry_artifact,
    }


def _promote_detector(registry_artifact: str, model_name: str, notes: str) -> Dict[str, Any]:
    registry_path = DATA_DIR / "runtime_model_registry.json"
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        registry = {
            "version": "1.0.0",
            "source": "shared-runtime-registry",
            "components": [],
        }

    components = registry.setdefault("components", [])
    component = next((item for item in components if item.get("component") == "person_detector"), None)
    if component is None:
        component = {
            "component": "person_detector",
            "display_name": "Person detector",
            "framework": "Ultralytics / PyTorch",
            "runtime": "ai-service",
            "status": "active",
            "target_model": "custom-yolo-person",
            "target_artifact": registry_artifact,
        }
        components.append(component)

    component.update({
        "current_model": model_name,
        "current_artifact": registry_artifact,
        "framework": component.get("framework") or "Ultralytics / PyTorch",
        "runtime": component.get("runtime") or "ai-service",
        "status": "active",
        "notes": notes,
    })
    registry["source"] = "shared-runtime-registry"
    registry["last_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return {"registry_path": str(registry_path), "component": component}


def _benchmark_fps(model: Any, images: Sequence[Path], frames: int, imgsz: int, device: str | None) -> Dict[str, Any]:
    if frames <= 0 or not images:
        return {"frames": 0, "fps": None, "mean_ms": None}

    sampled = [images[index % len(images)] for index in range(frames)]
    latencies_ms: List[float] = []
    for image_path in sampled:
        frame = cv2.imread(str(image_path))
        if frame is None:
            continue
        start = time.perf_counter()
        kwargs: Dict[str, Any] = {"imgsz": imgsz, "verbose": False}
        if device:
            kwargs["device"] = device
        _ = model.predict(frame, **kwargs)
        latencies_ms.append((time.perf_counter() - start) * 1000.0)

    if not latencies_ms:
        return {"frames": 0, "fps": None, "mean_ms": None}
    values = np.array(latencies_ms, dtype=float)
    return {
        "frames": len(latencies_ms),
        "fps": round(1000.0 / float(values.mean()), 2),
        "mean_ms": round(float(values.mean()), 2),
        "p95_ms": round(float(np.percentile(values, 95)), 2),
    }


def _train_and_validate(args: argparse.Namespace, split: Dict[str, Any]) -> Dict[str, Any]:
    from ultralytics import YOLO

    base_model = _resolve_base_model(args.base_model)
    run_name = args.run_name or f"sentinelcv_person_{time.strftime('%Y%m%d_%H%M%S')}"
    model = YOLO(str(base_model))

    train_kwargs: Dict[str, Any] = {
        "data": split["data_yaml"],
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "project": str(args.runs_dir),
        "name": run_name,
        "exist_ok": False,
    }
    if args.device:
        train_kwargs["device"] = args.device

    model.train(**train_kwargs)
    save_dir = Path(getattr(model.trainer, "save_dir", args.runs_dir / run_name))
    best_path = save_dir / "weights" / "best.pt"
    if not best_path.exists():
        raise FileNotFoundError(f"Training finished but best.pt was not found: {best_path}")

    trained_model = YOLO(str(best_path))
    val_kwargs: Dict[str, Any] = {"data": split["data_yaml"], "imgsz": args.imgsz, "verbose": False}
    if args.device:
        val_kwargs["device"] = args.device
    metrics = trained_model.val(**val_kwargs)
    box_metrics = getattr(metrics, "box", None)
    validation = {
        "map50": float(getattr(box_metrics, "map50", 0.0) or 0.0),
        "map50_95": float(getattr(box_metrics, "map", 0.0) or 0.0),
    }

    val_images = sorted((Path(split["split_dir"]) / "images" / "val").glob("*"))
    fps = _benchmark_fps(trained_model, val_images, args.benchmark_frames, args.imgsz, args.device or None)

    artifact = _copy_artifact(best_path, args.artifact_dir, args.model_name)
    return {
        "base_model": str(base_model),
        "run_dir": str(save_dir),
        "best_path": str(best_path),
        "artifact": artifact,
        "validation": validation,
        "fps": fps,
    }


def run(args: argparse.Namespace) -> Dict[str, Any]:
    pairs = _find_pairs(args.dataset_dir)
    if len(pairs) < args.min_images:
        raise RuntimeError(
            f"Need at least {args.min_images} labeled images, found {len(pairs)} in {args.dataset_dir}"
        )

    split_dir = args.dataset_dir / "splits" / "latest"
    split = _copy_split(pairs, split_dir, args.val_ratio, args.seed)
    result: Dict[str, Any] = {
        "dataset_dir": str(args.dataset_dir),
        "labeled_images": len(pairs),
        "split": split,
        "dry_run": args.dry_run,
    }

    if not args.dry_run:
        train_result = _train_and_validate(args, split)
        result["training"] = train_result
        if args.promote:
            result["promotion"] = _promote_detector(
                train_result["artifact"]["registry_artifact"],
                args.model_name,
                f"Promoted from detector distillation dataset with {len(pairs)} labeled hard frames.",
            )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"person_detector_distillation_{time.strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["output_path"] = str(output_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Train SentinelCV person detector from distillation captures.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--base-model", default="models/yolo11n.pt")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--runs-dir", type=Path, default=DATA_DIR / "training_runs" / "person_detector")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BENCHMARK_DIR)
    parser.add_argument("--model-name", default="SentinelCV-YOLO-Person")
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="")
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-images", type=int, default=10)
    parser.add_argument("--benchmark-frames", type=int, default=30)
    parser.add_argument("--run-name", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()

    if not 0.0 <= args.val_ratio < 1.0:
        raise SystemExit("--val-ratio must be >= 0 and < 1")
    if args.dry_run and args.promote:
        raise SystemExit("--promote requires a real training run, not --dry-run")

    result = run(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
