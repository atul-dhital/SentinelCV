"""
S16-BENCH: Performance benchmarking and accuracy validation helpers.

This benchmark exercises the current embedding search pipeline with:
1. Baseline single-frame identification
2. Multi-angle consensus identification
3. Latency profiling
4. A production-readiness summary
"""

import json
import logging
import os
import random
import sys
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("benchmark")

# Add backend to path when the script is executed directly.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.base import SessionLocal
from models import models
from services import visitor_service
from core.runtime_registry import benchmark_results_path


def generate_random_embedding(dim: int = 512) -> List[float]:
    return [random.uniform(-1, 1) for _ in range(dim)]


def add_noise(embedding: List[float], intensity: float = 0.05) -> List[float]:
    """Simulate camera noise and viewpoint variation on an embedding."""
    return [value + random.uniform(-intensity, intensity) for value in embedding]


def run_benchmark(sample_size: int = 50, output_path: Optional[str] = None) -> Dict[str, object]:
    db = SessionLocal()
    org_id = str(uuid.uuid4())
    visitors: List[tuple[models.Visitor, List[float]]] = []

    try:
        org = models.Organization(id=org_id, name="Auto Benchmarking Group")
        db.add(org)
        db.commit()

        logger.info("Starting benchmarking suite | organization=%s sample_size=%s", org_id, sample_size)
        logger.info("Seeding gallery with %s benchmark visitors", sample_size)

        for index in range(sample_size):
            visitor = models.Visitor(
                organization_id=org_id,
                name=f"Bench_Visitor_{index}",
                is_known=True,
                is_active=True,
            )
            db.add(visitor)
            db.flush()

            enrollment_embedding = generate_random_embedding()
            primary_face = models.FaceData(
                id=uuid.uuid4(),
                visitor_id=visitor.id,
                embedding=enrollment_embedding,
                image_url=f"face_images/bench_enroll_{visitor.id}.jpg",
                is_primary=True,
                quality_score=0.9,
            )
            db.add(primary_face)

            for angle in ["45_left", "45_right", "profile"]:
                angle_face = models.FaceData(
                    id=uuid.uuid4(),
                    visitor_id=visitor.id,
                    embedding=add_noise(enrollment_embedding, intensity=0.1),
                    image_url=f"face_images/bench_{visitor.id}_{angle}.jpg",
                    is_primary=False,
                    quality_score=0.8,
                    metadata={"angle": angle},
                )
                db.add(angle_face)

            visitors.append((visitor, enrollment_embedding))

        db.commit()

        results: Dict[str, object] = {
            "timestamp": datetime.now().isoformat(),
            "sample_size": sample_size,
            "baseline": {},
            "multi_angle": {},
            "summary": {},
        }

        logger.info("Running baseline single-frame identification test")
        correct_identifications = 0
        baseline_latencies: List[float] = []
        mrr_sum = 0.0

        for visitor, base_embedding in visitors:
            query_embedding = add_noise(base_embedding, intensity=0.03)

            start_time = time.time()
            match_result = visitor_service.search_visitor_by_embedding(
                db,
                org_id,
                query_embedding,
                threshold=0.5,
            )
            baseline_latencies.append((time.time() - start_time) * 1000)

            if match_result:
                matched_visitor, _confidence, _face_data_id, _metadata = match_result
                if str(matched_visitor.id) == str(visitor.id):
                    correct_identifications += 1
                    mrr_sum += 1.0
                else:
                    mrr_sum += 0.5

        results["baseline"] = {
            "accuracy": (correct_identifications / sample_size) * 100 if sample_size else 0.0,
            "avg_latency_ms": sum(baseline_latencies) / len(baseline_latencies) if baseline_latencies else 0.0,
            "mrr": mrr_sum / sample_size if sample_size else 0.0,
        }

        logger.info("Running multi-angle burst identification test")
        correct_identifications_burst = 0
        burst_latencies: List[float] = []

        for visitor, base_embedding in visitors:
            start_time = time.time()
            frame_predictions: List[str] = []

            for _ in range(5):
                query_embedding = add_noise(base_embedding, intensity=0.12)
                match_result = visitor_service.search_visitor_by_embedding(
                    db,
                    org_id,
                    query_embedding,
                    threshold=0.45,
                )
                if match_result:
                    frame_predictions.append(str(match_result[0].id))

            if frame_predictions:
                final_prediction = max(set(frame_predictions), key=frame_predictions.count)
                if final_prediction == str(visitor.id):
                    correct_identifications_burst += 1

            burst_latencies.append((time.time() - start_time) * 1000)

        results["multi_angle"] = {
            "accuracy": (correct_identifications_burst / sample_size) * 100 if sample_size else 0.0,
            "avg_burst_latency_ms": sum(burst_latencies) / len(burst_latencies) if burst_latencies else 0.0,
            "accuracy_boost_pct": (
                (correct_identifications_burst - correct_identifications) / sample_size * 100
                if sample_size
                else 0.0
            ),
        }

        results["summary"] = {
            "is_ready_for_prod": results["baseline"]["accuracy"] >= 95.0,
            "latency_target_met": results["baseline"]["avg_latency_ms"] <= 150.0,
            "recommendation": (
                "Ready for deployment"
                if results["baseline"]["accuracy"] >= 95.0
                else "Increase threshold tuning and improve enrollment quality auditing"
            ),
        }

        logger.info(
            "Benchmark complete | baseline_accuracy=%.2f multi_angle_accuracy=%.2f avg_latency_ms=%.2f",
            results["baseline"]["accuracy"],
            results["multi_angle"]["accuracy"],
            results["baseline"]["avg_latency_ms"],
        )

        destination = output_path or benchmark_results_path()
        destination_dir = os.path.dirname(destination)
        if destination_dir:
            os.makedirs(destination_dir, exist_ok=True)
        with open(destination, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2)

        logger.info("Benchmark results saved to %s", destination)
        return results
    finally:
        logger.info("Cleaning up benchmark seed data")
        try:
            db.rollback()
        except Exception:
            pass

        try:
            visitor_ids = [visitor.id for visitor, _embedding in visitors]
            if visitor_ids:
                db.query(models.FaceData).filter(
                    models.FaceData.visitor_id.in_(visitor_ids),
                ).delete(synchronize_session=False)
                db.query(models.Visitor).filter(
                    models.Visitor.id.in_(visitor_ids),
                ).delete(synchronize_session=False)

            db.query(models.Organization).filter(
                models.Organization.id == org_id,
            ).delete(synchronize_session=False)
            db.commit()
        except Exception as cleanup_error:
            db.rollback()
            logger.warning("Benchmark cleanup skipped: %s", cleanup_error)
        finally:
            db.close()


if __name__ == "__main__":
    requested_size = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_benchmark(requested_size)
