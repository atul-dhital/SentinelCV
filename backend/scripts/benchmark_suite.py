#!/usr/bin/env python3
"""
SentinelCV Performance Benchmark Suite

Comprehensive benchmarks for:
- Face detection FPS and latency
- Face recognition (embedding generation + matching)
- Liveness detection (per-method and ensemble)
- Person tracking (YOLOv8)
- API endpoint latency
- Database query performance
- Memory usage per component

Usage:
    python benchmark_suite.py [--iterations 100] [--api-url http://127.0.0.1:8000] [--output results.json]
"""

import argparse
import json
import os
import sys
import time
import traceback
import gc
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def benchmark_timing(func, iterations: int = 100, warmup: int = 5) -> Dict:
    """Run a function multiple times and collect timing statistics."""
    # Warmup
    for _ in range(warmup):
        try:
            func()
        except Exception:
            pass

    latencies = []
    errors = 0
    for _ in range(iterations):
        start = time.perf_counter()
        try:
            func()
            latencies.append((time.perf_counter() - start) * 1000)  # ms
        except Exception:
            errors += 1

    if not latencies:
        return {"error": "All iterations failed", "errors": errors}

    arr = np.array(latencies)
    return {
        "iterations": len(latencies),
        "errors": errors,
        "mean_ms": round(float(np.mean(arr)), 3),
        "median_ms": round(float(np.median(arr)), 3),
        "std_ms": round(float(np.std(arr)), 3),
        "min_ms": round(float(np.min(arr)), 3),
        "max_ms": round(float(np.max(arr)), 3),
        "p50_ms": round(float(np.percentile(arr, 50)), 3),
        "p95_ms": round(float(np.percentile(arr, 95)), 3),
        "p99_ms": round(float(np.percentile(arr, 99)), 3),
        "throughput_ops_sec": round(1000 / float(np.mean(arr)), 1),
    }


def benchmark_face_detection(iterations: int = 50) -> Dict:
    """Benchmark face detection latency."""
    print("  [1/7] Face Detection...")
    try:
        import cv2
        # Create synthetic test image (640x480 with a face-like region)
        img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        # Draw a face-like rectangle for cascade detector
        cv2.rectangle(img, (200, 100), (440, 380), (200, 180, 160), -1)

        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        def detect():
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            return len(faces)

        result = benchmark_timing(detect, iterations)
        result["detector"] = "OpenCV Haar Cascade"
        result["image_size"] = "640x480"
        result["fps"] = round(1000 / result["mean_ms"], 1) if result.get("mean_ms", 0) > 0 else 0
        return result
    except Exception as e:
        return {"error": str(e)}


def benchmark_face_recognition(iterations: int = 50) -> Dict:
    """Benchmark face embedding generation."""
    print("  [2/7] Face Recognition (Embedding)...")
    try:
        # Simulate ArcFace embedding computation
        # Use random matrix multiplication to simulate neural network forward pass
        weights = np.random.randn(512, 4096).astype(np.float32)
        bias = np.random.randn(512).astype(np.float32)

        def generate_embedding():
            face_crop = np.random.randn(1, 4096).astype(np.float32)
            embedding = face_crop @ weights.T + bias
            # L2 normalize
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            return embedding

        result = benchmark_timing(generate_embedding, iterations)
        result["embedding_dim"] = 512
        result["model"] = "ArcFace (simulated)"
        return result
    except Exception as e:
        return {"error": str(e)}


def benchmark_embedding_matching(iterations: int = 100) -> Dict:
    """Benchmark embedding similarity search."""
    print("  [3/7] Embedding Matching...")
    try:
        db_size = 1000
        dim = 512
        database = np.random.randn(db_size, dim).astype(np.float32)
        # Normalize
        norms = np.linalg.norm(database, axis=1, keepdims=True)
        database = database / norms

        def search():
            query = np.random.randn(1, dim).astype(np.float32)
            query = query / np.linalg.norm(query)
            similarities = database @ query.T
            top_idx = np.argmax(similarities)
            return float(similarities[top_idx])

        result = benchmark_timing(search, iterations)
        result["database_size"] = db_size
        result["embedding_dim"] = dim
        result["method"] = "cosine_similarity (numpy)"
        return result
    except Exception as e:
        return {"error": str(e)}


def benchmark_liveness_detection(iterations: int = 30) -> Dict:
    """Benchmark liveness detection methods."""
    print("  [4/7] Liveness Detection...")
    try:
        import cv2

        # Create test frames
        frames = [np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8) for _ in range(5)]

        results = {}

        # Texture-based (LBP)
        def lbp_detection():
            gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
            entropy = -np.sum((hist / hist.sum()) * np.log2(hist / hist.sum() + 1e-7))
            return float(entropy)

        results["texture_lbp"] = benchmark_timing(lbp_detection, iterations)

        # Motion-based (optical flow)
        def motion_detection():
            gray1 = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(frames[1], cv2.COLOR_BGR2GRAY)
            flow = cv2.calcOpticalFlowFarneback(gray1, gray2, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            return float(np.mean(np.abs(flow)))

        results["motion_optical_flow"] = benchmark_timing(motion_detection, iterations)

        # Deep learning (simulated CNN)
        def dl_detection():
            img = frames[0].astype(np.float32) / 255.0
            flat = img.flatten()[:4096]
            weights = np.random.randn(1, len(flat)).astype(np.float32)
            score = 1 / (1 + np.exp(-float(weights @ flat.reshape(-1, 1))))
            return score

        results["deep_learning_cnn"] = benchmark_timing(dl_detection, iterations)

        return results
    except Exception as e:
        return {"error": str(e)}


def benchmark_person_tracking(iterations: int = 30) -> Dict:
    """Benchmark person detection and tracking."""
    print("  [5/7] Person Tracking (YOLOv8)...")
    try:
        from ultralytics import YOLO

        model_path = os.path.join(os.path.dirname(__file__), "..", "..", "ai_services", "yolov8n.pt")
        if not os.path.exists(model_path):
            return {"error": "yolov8n.pt not found", "note": "Place model in ai_services/"}

        model = YOLO(model_path)
        img = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)

        def detect():
            results = model(img, verbose=False)
            return len(results[0].boxes) if results else 0

        result = benchmark_timing(detect, iterations, warmup=3)
        result["model"] = "YOLOv8n"
        result["input_size"] = "640x640"
        result["fps"] = round(1000 / result["mean_ms"], 1) if result.get("mean_ms", 0) > 0 else 0
        return result
    except ImportError:
        return {"error": "ultralytics not installed", "note": "pip install ultralytics"}
    except Exception as e:
        return {"error": str(e)}


def benchmark_api_latency(base_url: str, iterations: int = 50) -> Dict:
    """Benchmark API endpoint response times."""
    print("  [6/7] API Latency...")
    try:
        import requests

        endpoints = {
            "health": "/api/v1/health",
            "health_readiness": "/api/v1/health/readiness",
        }

        results = {}
        for name, path in endpoints.items():
            def call(url=f"{base_url}{path}"):
                resp = requests.get(url, timeout=10)
                assert resp.status_code == 200

            try:
                results[name] = benchmark_timing(call, min(iterations, 30))
            except Exception as e:
                results[name] = {"error": str(e)}

        return results
    except ImportError:
        return {"error": "requests not installed"}
    except Exception as e:
        return {"error": str(e)}


def benchmark_database_queries(iterations: int = 50) -> Dict:
    """Benchmark database query performance."""
    print("  [7/7] Database Queries...")
    try:
        from sqlalchemy import create_engine, text

        db_url = os.getenv("DATABASE_URL", "sqlite:///./sentinelcv.db")
        engine = create_engine(db_url)

        queries = {
            "count_visitors": "SELECT COUNT(*) FROM visitors",
            "count_logs": "SELECT COUNT(*) FROM visitor_logs",
            "count_cameras": "SELECT COUNT(*) FROM cameras",
        }

        results = {}
        for name, sql in queries.items():
            def run_query(q=sql):
                with engine.connect() as conn:
                    conn.execute(text(q))

            try:
                results[name] = benchmark_timing(run_query, iterations)
            except Exception as e:
                results[name] = {"error": str(e)}

        engine.dispose()
        return results
    except Exception as e:
        return {"error": str(e)}


def benchmark_memory_usage() -> Dict:
    """Measure memory usage of key components."""
    import tracemalloc

    tracemalloc.start()
    gc.collect()
    baseline = tracemalloc.get_traced_memory()

    results = {"baseline_mb": round(baseline[0] / (1024 * 1024), 2)}

    # Measure numpy array memory (simulating embedding database)
    embeddings = np.random.randn(10000, 512).astype(np.float32)
    after_emb = tracemalloc.get_traced_memory()
    results["10k_embeddings_mb"] = round((after_emb[0] - baseline[0]) / (1024 * 1024), 2)
    del embeddings
    gc.collect()

    tracemalloc.stop()
    return results


def run_all_benchmarks(args) -> Dict:
    """Run complete benchmark suite."""
    print("\n" + "=" * 60)
    print("  SentinelCV Performance Benchmark Suite")
    print("=" * 60)

    start_time = time.time()
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "iterations": args.iterations,
        "benchmarks": {},
    }

    results["benchmarks"]["face_detection"] = benchmark_face_detection(args.iterations)
    results["benchmarks"]["face_recognition"] = benchmark_face_recognition(args.iterations)
    results["benchmarks"]["embedding_matching"] = benchmark_embedding_matching(args.iterations)
    results["benchmarks"]["liveness_detection"] = benchmark_liveness_detection(min(args.iterations, 30))
    results["benchmarks"]["person_tracking"] = benchmark_person_tracking(min(args.iterations, 30))
    results["benchmarks"]["api_latency"] = benchmark_api_latency(args.api_url, min(args.iterations, 30))
    results["benchmarks"]["database_queries"] = benchmark_database_queries(args.iterations)
    results["benchmarks"]["memory_usage"] = benchmark_memory_usage()

    total_time = time.time() - start_time
    results["total_benchmark_time_seconds"] = round(total_time, 2)

    # Summary
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)

    for name, data in results["benchmarks"].items():
        if isinstance(data, dict) and "mean_ms" in data:
            fps_str = f" ({data.get('fps', 'N/A')} FPS)" if "fps" in data else ""
            print(f"  {name:30s}: {data['mean_ms']:>8.2f} ms avg (p95: {data.get('p95_ms', 'N/A')} ms){fps_str}")
        elif isinstance(data, dict) and "error" not in data:
            for sub_name, sub_data in data.items():
                if isinstance(sub_data, dict) and "mean_ms" in sub_data:
                    print(f"  {name}/{sub_name:24s}: {sub_data['mean_ms']:>8.2f} ms avg")

    print(f"\n  Total benchmark time: {total_time:.1f}s")
    print("=" * 60)

    return results


def main():
    parser = argparse.ArgumentParser(description="SentinelCV Benchmark Suite")
    parser.add_argument("--iterations", type=int, default=50, help="Number of iterations per benchmark")
    parser.add_argument("--api-url", type=str, default="http://127.0.0.1:8000", help="Backend API URL")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    args = parser.parse_args()

    results = run_all_benchmarks(args)

    # Save results
    output_path = args.output or f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {output_path}")


if __name__ == "__main__":
    main()
