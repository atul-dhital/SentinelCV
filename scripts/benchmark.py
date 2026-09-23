"""
Performance benchmarking suite for SentinelCV system.

Measures:
- FPS (frames per second) for detection pipeline
- Latency (ms) for individual operations
- Accuracy metrics for face recognition and liveness detection
"""

import argparse
import os
import sys
import time
import numpy as np
import cv2
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import json

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_SERVICE_ROOT = os.path.join(BACKEND_ROOT, "backend")
AI_SERVICE_ROOT = os.path.join(BACKEND_ROOT, "ai_services")
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
if BACKEND_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_SERVICE_ROOT)
if AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, AI_SERVICE_ROOT)

from services.liveness_service import LivenessDetectionService
from schemas.schemas import LivenessConfig

try:
    from ai_services.tracker import PersonTracker
    _YOLO_AVAILABLE = True
except Exception:
    PersonTracker = None
    _YOLO_AVAILABLE = False


class BenchmarkResult:
    """Container for benchmark results."""
    
    def __init__(self, name: str):
        self.name = name
        self.times: List[float] = []
        self.start_time = None
    
    def start(self):
        """Mark start of operation."""
        self.start_time = time.perf_counter()
    
    def end(self):
        """Mark end of operation and record time."""
        if self.start_time is None:
            raise ValueError("start() must be called before end()")
        elapsed = (time.perf_counter() - self.start_time) * 1000  # Convert to ms
        self.times.append(elapsed)
    
    @property
    def avg_ms(self) -> float:
        """Average time in milliseconds."""
        if not self.times:
            return 0.0
        return np.mean(self.times)
    
    @property
    def min_ms(self) -> float:
        """Minimum time in milliseconds."""
        return np.min(self.times) if self.times else 0.0
    
    @property
    def max_ms(self) -> float:
        """Maximum time in milliseconds."""
        return np.max(self.times) if self.times else 0.0
    
    @property
    def std_ms(self) -> float:
        """Standard deviation in milliseconds."""
        return np.std(self.times) if self.times else 0.0
    
    @property
    def fps(self) -> float:
        """Estimated FPS (1000 / avg_ms)."""
        return 1000.0 / self.avg_ms if self.avg_ms > 0 else 0.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "samples": len(self.times),
            "avg_ms": round(self.avg_ms, 2),
            "min_ms": round(self.min_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "std_ms": round(self.std_ms, 2),
            "fps": round(self.fps, 2),
        }


def create_synthetic_frames(
    num_frames: int = 60,
    height: int = 480,
    width: int = 640,
) -> List[np.ndarray]:
    """Create synthetic video frames for benchmarking."""
    frames = []
    for i in range(num_frames):
        # Create a frame with some variation
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Add a simulated face region (rectangle)
        x, y, w, h = 200, 150, 240, 300
        frame[y:y+h, x:x+w] = [120 + (i % 30), 100 + (i % 30), 80 + (i % 30)]
        
        # Add some noise
        noise = np.random.randint(-10, 10, frame.shape, dtype=np.int16)
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        
        frames.append(frame)
    
    return frames


class LivenessServiceBenchmark:
    """Benchmark suite for LivenessDetectionService."""
    
    def __init__(self):
        self.service = LivenessDetectionService()
        self.results: Dict[str, BenchmarkResult] = {}
    
    def record(self, name: str) -> BenchmarkResult:
        """Get or create a benchmark result tracker."""
        if name not in self.results:
            self.results[name] = BenchmarkResult(name)
        return self.results[name]
    
    def benchmark_texture_detection(self, num_samples: int = 50):
        """Benchmark texture-based liveness detection."""
        print(f"\n[Texture Detection] Running {num_samples} samples...")
        
        frames = create_synthetic_frames(num_frames=5)
        frame = frames[0]
        
        for i in range(num_samples):
            result = self.record("texture_detection")
            result.start()
            score, details = self.service.detect_liveness_texture_based(frame)
            result.end()
            
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{num_samples} samples")
    
    def benchmark_motion_detection(self, num_samples: int = 30):
        """Benchmark motion-based liveness detection."""
        print(f"\n[Motion Detection] Running {num_samples} samples...")
        
        frames = create_synthetic_frames(num_frames=30)
        
        for i in range(num_samples):
            result = self.record("motion_detection")
            result.start()
            score, details = self.service.detect_liveness_motion_based(frames)
            result.end()
            
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{num_samples} samples")
    
    def benchmark_deep_learning_detection(self, num_samples: int = 40):
        """Benchmark deep learning-based detection."""
        print(f"\n[Deep Learning Detection] Running {num_samples} samples...")
        
        frames = create_synthetic_frames(num_frames=5)
        frame = frames[0]
        
        for i in range(num_samples):
            result = self.record("deep_learning_detection")
            result.start()
            score, details = self.service.detect_liveness_deep_learning(frame)
            result.end()
            
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{num_samples} samples")
    
    def benchmark_ensemble_detection(self, num_samples: int = 20):
        """Benchmark ensemble detection."""
        print(f"\n[Ensemble Detection] Running {num_samples} samples...")
        
        frames = create_synthetic_frames(num_frames=30)
        frame = frames[0]
        
        for i in range(num_samples):
            result = self.record("ensemble_detection")
            result.start()
            detection_result = self.service.ensemble_detection(
                frame=frame,
                frames=frames,
                methods=["texture", "motion", "deep_learning"],
            )
            result.end()
            
            if (i + 1) % 5 == 0:
                print(f"  Processed {i + 1}/{num_samples} samples")
    
    def benchmark_blink_challenge(self, num_samples: int = 20):
        """Benchmark blink challenge verification."""
        print(f"\n[Blink Challenge] Running {num_samples} samples...")
        
        frames = create_synthetic_frames(num_frames=30)
        
        for i in range(num_samples):
            result = self.record("blink_challenge_verification")
            result.start()
            passed, confidence, details = self.service._verify_blink_challenge(frames)
            result.end()
            
            if (i + 1) % 5 == 0:
                print(f"  Processed {i + 1}/{num_samples} samples")
    
    def benchmark_head_turn_challenge(self, num_samples: int = 20):
        """Benchmark head turn challenge verification."""
        print(f"\n[Head Turn Challenge] Running {num_samples} samples...")
        
        frames = create_synthetic_frames(num_frames=30)
        
        for i in range(num_samples):
            result = self.record("head_turn_challenge_verification")
            result.start()
            passed, confidence, details = self.service._verify_head_turn_challenge(frames)
            result.end()
            
            if (i + 1) % 5 == 0:
                print(f"  Processed {i + 1}/{num_samples} samples")
    
    def benchmark_smile_challenge(self, num_samples: int = 20):
        """Benchmark smile challenge verification."""
        print(f"\n[Smile Challenge] Running {num_samples} samples...")
        
        frames = create_synthetic_frames(num_frames=30)
        
        for i in range(num_samples):
            result = self.record("smile_challenge_verification")
            result.start()
            passed, confidence, details = self.service._verify_smile_challenge(frames)
            result.end()
            
            if (i + 1) % 5 == 0:
                print(f"  Processed {i + 1}/{num_samples} samples")
    
    def benchmark_frame_processing(self, num_samples: int = 100):
        """Benchmark frame processing utilities."""
        print(f"\n[Frame Processing] Running {num_samples} samples...")
        
        frame = create_synthetic_frames(num_frames=1)[0]
        
        # Benchmark grayscale conversion
        result = self.record("grayscale_conversion")
        for i in range(num_samples):
            result.start()
            gray = self.service._to_grayscale_uint8(frame)
            result.end()
    
    def run_full_benchmark(self):
        """Run comprehensive benchmark suite (liveness + optional YOLO)."""
        print("=" * 60)
        print("SentinelCV Performance Benchmarking Suite")
        print("=" * 60)
        print(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

        self.run_liveness_benchmark()
        self.benchmark_person_detection()

        self._print_results()
        self._save_results()

    def run_liveness_benchmark(self) -> None:
        """Run the liveness-only benchmark suite."""
        self.benchmark_texture_detection(num_samples=50)
        self.benchmark_motion_detection(num_samples=30)
        self.benchmark_deep_learning_detection(num_samples=40)
        self.benchmark_ensemble_detection(num_samples=20)

        self.benchmark_blink_challenge(num_samples=20)
        self.benchmark_head_turn_challenge(num_samples=20)
        self.benchmark_smile_challenge(num_samples=20)

        self.benchmark_frame_processing(num_samples=100)

    def _resolve_yolo_models(self, model_paths: Optional[List[str]] = None) -> List[Tuple[str, str]]:
        if model_paths is None:
            model_paths = ["yolo11n.pt", "yolov8n.pt"]

        ai_dir = Path(BACKEND_ROOT) / "ai_services"
        resolved: List[Tuple[str, str]] = []

        for candidate in model_paths:
            options = [candidate, str(ai_dir / candidate)]
            for option in options:
                if option and os.path.exists(option):
                    label = Path(option).stem
                    resolved.append((label, option))
                    break

        return resolved

    def benchmark_person_detection(self, num_samples: int = 30, model_paths: Optional[List[str]] = None) -> None:
        """Benchmark YOLO person detection performance for configured models."""
        if not _YOLO_AVAILABLE:
            print("\n[YOLO Detection] Skipped (ultralytics not available)")
            return

        models = self._resolve_yolo_models(model_paths)
        if not models:
            print("\n[YOLO Detection] Skipped (no YOLO model artifacts found)")
            return

        frame = create_synthetic_frames(num_frames=1)[0]
        for label, model_path in models:
            print(f"\n[YOLO Detection] {label} @ {model_path} ({num_samples} samples)")
            tracker = PersonTracker(model_path=model_path, model_name=label)
            for i in range(num_samples):
                result = self.record(f"person_detection_{label}")
                result.start()
                _ = tracker.model.predict(frame, classes=[0], verbose=False)
                result.end()
                if (i + 1) % 10 == 0:
                    print(f"  Processed {i + 1}/{num_samples} samples")
    
    def _print_results(self):
        """Print benchmark results in a nicely formatted table."""
        print("\n" + "=" * 80)
        print("BENCHMARK RESULTS")
        print("=" * 80)
        
        # Sort by operation name for consistent output
        sorted_results = sorted(self.results.items(), key=lambda x: x[0])
        
        print(f"{'Operation':<40} {'FPS':<8} {'Avg(ms)':<10} {'Min(ms)':<10} {'Max(ms)':<10}")
        print("-" * 80)
        
        for name, result in sorted_results:
            print(
                f"{name:<40} "
                f"{result.fps:<8.2f} "
                f"{result.avg_ms:<10.2f} "
                f"{result.min_ms:<10.2f} "
                f"{result.max_ms:<10.2f}"
            )
        
        print("=" * 80)
        
        # Print performance summary
        print("\nPERFORMANCE SUMMARY:")
        
        detection_methods = [r for r in self.results.values() 
                            if "detection" in r.name and "challenge" not in r.name]
        challenge_methods = [r for r in self.results.values() 
                            if "challenge_verification" in r.name]
        
        if detection_methods:
            avg_detection_fps = np.mean([r.fps for r in detection_methods])
            print(f"  Average Detection FPS: {avg_detection_fps:.2f}")
        
        if challenge_methods:
            avg_challenge_fps = np.mean([r.fps for r in challenge_methods])
            print(f"  Average Challenge Verification FPS: {avg_challenge_fps:.2f}")
        
        ensemble_result = self.results.get("ensemble_detection")
        if ensemble_result:
            print(f"  Ensemble Detection: {ensemble_result.fps:.2f} FPS, {ensemble_result.avg_ms:.2f}ms avg")
    
    def _save_results(self):
        """Save benchmark results to JSON file."""
        output_file = Path(BACKEND_ROOT) / "benchmark_results.json"
        
        results_dict = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "benchmarks": {name: result.to_dict() 
                          for name, result in self.results.items()},
            "summary": {
                "total_tests": sum(len(r.times) for r in self.results.values()),
                "detection_fps": np.mean([r.fps for r in self.results.values()
                                        if "detection" in r.name]).item()
                if any("detection" in r.name for r in self.results.values())
                else 0,
                "challenge_fps": np.mean([r.fps for r in self.results.values()
                                        if "challenge" in r.name]).item()
                if any("challenge" in r.name for r in self.results.values())
                else 0,
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(results_dict, f, indent=2)
        
        print(f"\nResults saved to: {output_file}")


def main():
    """Run benchmarking suite."""
    parser = argparse.ArgumentParser(description="SentinelCV benchmarking suite")
    parser.add_argument(
        "--component",
        choices=["full", "liveness", "person_detection"],
        default="full",
        help="Benchmark component to run",
    )
    parser.add_argument(
        "--yolo-models",
        nargs="*",
        default=None,
        help="Optional YOLO model paths to benchmark",
    )
    args = parser.parse_args()

    benchmark = LivenessServiceBenchmark()
    if args.component == "liveness":
        benchmark.run_liveness_benchmark()
        benchmark._print_results()
        benchmark._save_results()
        return

    if args.component == "person_detection":
        benchmark.benchmark_person_detection(model_paths=args.yolo_models)
        benchmark._print_results()
        benchmark._save_results()
        return

    benchmark.run_full_benchmark()


if __name__ == "__main__":
    main()
