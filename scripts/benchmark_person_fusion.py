"""Benchmark SentinelCV person detector modes on webcam, video, or synthetic frames.

Examples:
    python scripts/benchmark_person_fusion.py --mode yolo_only --frames 30
    python scripts/benchmark_person_fusion.py --mode fallback_fusion --source 0 --frames 60
    python scripts/benchmark_person_fusion.py --mode fallback_fusion --source sample.mp4 --secondary-url http://127.0.0.1:9001/infer
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, Iterable, List, Optional

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICES = REPO_ROOT / "ai_services"
if str(AI_SERVICES) not in sys.path:
    sys.path.insert(0, str(AI_SERVICES))


def _load_psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:
        return None


def _synthetic_frames(count: int, width: int, height: int) -> Iterable[np.ndarray]:
    for index in range(count):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        x = 40 + (index * 7) % max(1, width - 120)
        cv2.rectangle(frame, (x, 40), (x + 60, height - 30), (220, 220, 220), -1)
        cv2.circle(frame, (x + 30, 25), 20, (180, 180, 180), -1)
        yield frame


def _capture_frames(source: str, count: int, width: int, height: int) -> Iterable[np.ndarray]:
    if source == "synthetic":
        yield from _synthetic_frames(count, width, height)
        return

    video_source: Any = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source: {source}")

    try:
        captured = 0
        while captured < count:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            captured += 1
            yield frame
    finally:
        cap.release()


def _summarize_latencies(latencies_ms: List[float]) -> Dict[str, Optional[float]]:
    if not latencies_ms:
        return {"mean_ms": None, "min_ms": None, "max_ms": None, "p95_ms": None}
    values = np.array(latencies_ms, dtype=float)
    return {
        "mean_ms": round(float(values.mean()), 2),
        "min_ms": round(float(values.min()), 2),
        "max_ms": round(float(values.max()), 2),
        "p95_ms": round(float(np.percentile(values, 95)), 2),
    }


def run_benchmark(args: argparse.Namespace) -> Dict[str, Any]:
    os.environ["PERSON_DETECTOR_MODE"] = args.mode
    if args.secondary_url:
        os.environ["PERSON_SECONDARY_INFERENCE_URL"] = args.secondary_url
    if args.secondary_model:
        os.environ["PERSON_SECONDARY_MODEL"] = args.secondary_model
    os.environ["PERSON_SECONDARY_EVERY_N_FRAMES"] = str(args.secondary_every_n_frames)
    os.environ["PERSON_SECONDARY_TRIGGER_CONFIDENCE"] = str(args.secondary_trigger_confidence)
    os.environ["PERSON_SECONDARY_TIMEOUT_SECONDS"] = str(args.secondary_timeout_seconds)
    if args.capture:
        os.environ["PERSON_DISTILLATION_CAPTURE"] = "1"
        if args.capture_dir:
            os.environ["PERSON_DISTILLATION_DIR"] = args.capture_dir
        os.environ["PERSON_DISTILLATION_MAX_PER_RUN"] = str(args.capture_max)
        os.environ["PERSON_DISTILLATION_MIN_INTERVAL_SECONDS"] = str(args.capture_min_interval_seconds)

    from tracker import PersonTracker

    psutil = _load_psutil()
    process = psutil.Process(os.getpid()) if psutil else None
    if process:
        process.cpu_percent(interval=None)

    startup_start = time.perf_counter()
    tracker = PersonTracker()
    startup_ms = (time.perf_counter() - startup_start) * 1000.0

    frame_count = 0
    total_detections = 0
    missed_frames = 0
    source_counts: Dict[str, int] = {}
    latencies_ms: List[float] = []

    run_start = time.perf_counter()
    for frame in _capture_frames(args.source, args.frames, args.width, args.height):
        start = time.perf_counter()
        detections = tracker.detect_persons(frame, conf_threshold=args.confidence)
        latencies_ms.append((time.perf_counter() - start) * 1000.0)

        frame_count += 1
        total_detections += len(detections)
        if not detections:
            missed_frames += 1
        for detection in detections:
            source = str(detection.get("source") or "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1

    elapsed_seconds = time.perf_counter() - run_start
    memory_mb = None
    cpu_percent = None
    if process:
        memory_mb = round(process.memory_info().rss / (1024 * 1024), 2)
        cpu_percent = round(process.cpu_percent(interval=None), 2)

    fps = frame_count / elapsed_seconds if elapsed_seconds > 0 else 0.0
    result = {
        "mode": args.mode,
        "source": args.source,
        "secondary_url_configured": bool(args.secondary_url or os.getenv("PERSON_SECONDARY_INFERENCE_URL")),
        "secondary_model": os.getenv("PERSON_SECONDARY_MODEL", "rfdetr-nano"),
        "frames": frame_count,
        "startup_ms": round(startup_ms, 2),
        "elapsed_seconds": round(elapsed_seconds, 2),
        "fps": round(fps, 2),
        "total_detections": total_detections,
        "avg_detections_per_frame": round(total_detections / frame_count, 2) if frame_count else 0.0,
        "missed_frames": missed_frames,
        "missed_frame_rate": round(missed_frames / frame_count, 4) if frame_count else 0.0,
        "detection_sources": source_counts,
        "latency": _summarize_latencies(latencies_ms),
        "process_cpu_percent": cpu_percent,
        "process_memory_mb": memory_mb,
    }

    if args.output:
        output_path = Path(args.output)
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = REPO_ROOT / "backend" / "data" / "benchmarks" / f"person_fusion_benchmark_{stamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["output_path"] = str(output_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark SentinelCV person detector fusion.")
    parser.add_argument("--source", default="synthetic", help="synthetic, webcam index like 0, RTSP URL, or video path")
    parser.add_argument("--frames", type=int, default=30, help="Number of frames to process")
    parser.add_argument("--width", type=int, default=640, help="Synthetic frame width")
    parser.add_argument("--height", type=int, default=480, help="Synthetic frame height")
    parser.add_argument("--mode", choices=["yolo_only", "fallback_fusion"], default="fallback_fusion")
    parser.add_argument("--confidence", type=float, default=0.3)
    parser.add_argument("--secondary-url", default="", help="Local RF-DETR/Roboflow-compatible inference endpoint")
    parser.add_argument("--secondary-model", default="rfdetr-nano")
    parser.add_argument("--secondary-every-n-frames", type=int, default=10)
    parser.add_argument("--secondary-trigger-confidence", type=float, default=0.65)
    parser.add_argument("--secondary-timeout-seconds", type=float, default=0.6)
    parser.add_argument("--capture", action="store_true", help="Capture hard frames for detector distillation")
    parser.add_argument("--capture-dir", default="", help="Override PERSON_DISTILLATION_DIR")
    parser.add_argument("--capture-max", type=int, default=200)
    parser.add_argument("--capture-min-interval-seconds", type=float, default=2.0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    result = run_benchmark(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
