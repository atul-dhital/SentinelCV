"""
Performance Optimization Module for SentinelCV AI Service.

Provides batch processing, GPU acceleration hints, and performance monitoring.
"""

import time
import cv2
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class PerformanceConfig:
    """Configuration for performance optimization."""
    target_fps: float = 30.0
    batch_size: int = 8
    use_gpu: bool = False
    use_half_precision: bool = False
    max_resolution: Tuple[int, int] = (1920, 1080)
    frame_skip_threshold: float = 80.0  # CPU threshold for frame skipping


class PerformanceMonitor:
    """Monitor and track performance metrics."""
    
    def __init__(self):
        self._frame_times: List[float] = []
        self._detection_times: List[float] = []
        self._embedding_times: List[float] = []
        self._max_history = 100
        
    def record_frame_time(self, duration: float):
        """Record time taken to process a frame."""
        self._frame_times.append(duration)
        if len(self._frame_times) > self._max_history:
            self._frame_times = self._frame_times[-self._max_history:]
    
    def record_detection_time(self, duration: float):
        """Record time taken for face detection."""
        self._detection_times.append(duration)
        if len(self._detection_times) > self._max_history:
            self._detection_times = self._detection_times[-self._max_history:]
    
    def record_embedding_time(self, duration: float):
        """Record time taken for embedding generation."""
        self._embedding_times.append(duration)
        if len(self._embedding_times) > self._max_history:
            self._embedding_times = self._embedding_times[-self._max_history:]
    
    def get_avg_frame_time(self) -> float:
        """Get average frame processing time."""
        if not self._frame_times:
            return 0.0
        return sum(self._frame_times) / len(self._frame_times)
    
    def get_avg_fps(self) -> float:
        """Get average FPS."""
        avg_time = self.get_avg_frame_time()
        if avg_time > 0:
            return 1.0 / avg_time
        return 0.0
    
    def get_stats(self) -> Dict[str, float]:
        """Get all performance statistics."""
        return {
            "avg_frame_time_ms": self.get_avg_frame_time() * 1000,
            "avg_fps": self.get_avg_fps(),
            "avg_detection_ms": (sum(self._detection_times) / len(self._detection_times) * 1000) if self._detection_times else 0,
            "avg_embedding_ms": (sum(self._embedding_times) / len(self._embedding_times) * 1000) if self._embedding_times else 0,
            "frames_processed": len(self._frame_times),
        }


class BatchProcessor:
    """Process multiple frames in batch for better GPU utilization."""
    
    def __init__(self, config: PerformanceConfig = None):
        self.config = config or PerformanceConfig()
        self.monitor = PerformanceMonitor()
        
    def preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """Preprocess frame for optimal processing."""
        h, w = frame.shape[:2]
        
        max_w, max_h = self.config.max_resolution
        if w > max_w or h > max_h:
            scale = min(max_w / w, max_h / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        return frame
    
    def should_skip_frame(self, cpu_usage: float = 0.0) -> bool:
        """Determine if frame should be skipped based on CPU usage."""
        if cpu_usage > self.config.frame_skip_threshold:
            return True
        return False
    
    def calculate_optimal_stride(self, target_fps: float, current_fps: float) -> int:
        """Calculate frame stride to meet target FPS."""
        if current_fps >= target_fps:
            return 1
        
        ratio = target_fps / current_fps
        return max(1, int(ratio))
    
    def optimize_batch_size(self, available_memory_mb: float) -> int:
        """Adjust batch size based on available memory."""
        if available_memory_mb > 4096:
            return 16
        elif available_memory_mb > 2048:
            return 8
        elif available_memory_mb > 1024:
            return 4
        return 2


class VideoFrameBuffer:
    """Efficient frame buffer for RTSP streams."""
    
    def __init__(self, max_size: int = 30):
        self._buffer: List[np.ndarray] = []
        self._max_size = max_size
        self._lock = False
        
    def push(self, frame: np.ndarray):
        """Add frame to buffer."""
        if len(self._buffer) >= self._max_size:
            self._buffer.pop(0)
        self._buffer.append(frame.copy())
    
    def get_latest(self) -> Optional[np.ndarray]:
        """Get latest frame."""
        if self._buffer:
            return self._buffer[-1].copy()
        return None
    
    def get_batch(self, size: int) -> List[np.ndarray]:
        """Get batch of frames."""
        return [f.copy() for f in self._buffer[-size:]]
    
    def clear(self):
        """Clear buffer."""
        self._buffer.clear()
    
    @property
    def size(self) -> int:
        return len(self._buffer)


class AdaptiveProcessing:
    """Adaptive processing based on scene complexity."""
    
    def __init__(self):
        self._scene_complexity = 0.0
        self._face_count_history: List[int] = []
        
    def analyze_scene(self, frame: np.ndarray) -> float:
        """Analyze scene complexity based on edge density."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / edges.size
        return edge_density
    
    def update_face_count(self, face_count: int):
        """Update face count history."""
        self._face_count_history.append(face_count)
        if len(self._face_count_history) > 10:
            self._face_count_history.pop(0)
    
    def should_process_every_frame(self) -> bool:
        """Determine if every frame should be processed."""
        if not self._face_count_history:
            return True
        
        avg_faces = sum(self._face_count_history) / len(self._face_count_history)
        return avg_faces < 2
    
    def get_processing_interval(self) -> int:
        """Get optimal processing interval."""
        if not self._face_count_history:
            return 1
        
        avg_faces = sum(self._face_count_history) / len(self._face_count_history)
        
        if avg_faces > 5:
            return 1
        elif avg_faces > 2:
            return 2
        elif avg_faces > 0:
            return 3
        return 5


class FaceQualityScorer:
    """Score face quality for best frame selection."""
    
    def __init__(self):
        self.min_face_size = 100
        self.max_face_size = 500
        
    def score_face(self, face_bbox: Tuple[int, int, int, int], 
                   frame: np.ndarray) -> float:
        """Score a face based on multiple quality factors."""
        x1, y1, x2, y2 = face_bbox
        face_width = x2 - x1
        face_height = y2 - y1
        
        size_score = self._score_size(face_width, face_height)
        brightness_score = self._score_brightness(frame[y1:y2, x1:x2])
        sharpness_score = self._score_sharpness(frame[y1:y2, x1:x2])
        center_score = self._score_center(face_width, face_height, frame.shape[1], frame.shape[0])
        
        weights = {
            "size": 0.3,
            "brightness": 0.2,
            "sharpness": 0.3,
            "center": 0.2
        }
        
        total = (
            size_score * weights["size"] +
            brightness_score * weights["brightness"] +
            sharpness_score * weights["sharpness"] +
            center_score * weights["center"]
        )
        
        return total
    
    def _score_size(self, width: int, height: int) -> float:
        """Score based on face size."""
        area = width * height
        
        if area < self.min_face_size ** 2:
            return 0.0
        elif area > self.max_face_size ** 2:
            return 0.5
        
        ideal = (self.min_face_size + self.max_face_size) / 2
        distance = abs(area - ideal ** 2)
        max_distance = (ideal ** 2 - self.min_face_size ** 2)
        
        return 1.0 - (distance / max_distance)
    
    def _score_brightness(self, face_region: np.ndarray) -> float:
        """Score based on face brightness."""
        if face_region.size == 0:
            return 0.0
            
        gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
        mean_brightness = np.mean(gray)
        
        if mean_brightness < 30:
            return 0.0
        elif mean_brightness > 220:
            return 0.0
        
        ideal = 128
        return 1.0 - abs(mean_brightness - ideal) / 128
    
    def _score_sharpness(self, face_region: np.ndarray) -> float:
        """Score based on face sharpness (blur detection)."""
        if face_region.size == 0:
            return 0.0
            
        gray = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        if laplacian_var < 50:
            return 0.0
        elif laplacian_var > 500:
            return 1.0
        
        return (laplacian_var - 50) / 450
    
    def _score_center(self, face_w: int, face_h: int, 
                      frame_w: int, frame_h: int) -> float:
        """Score based on face position (center is better)."""
        center_x = face_w / 2
        center_y = face_h / 2
        
        frame_center_x = frame_w / 2
        frame_center_y = frame_h / 2
        
        distance = ((center_x - frame_center_x) ** 2 + 
                   (center_y - frame_center_y) ** 2) ** 0.5
        
        max_distance = ((frame_w / 2) ** 2 + (frame_h / 2) ** 2) ** 0.5
        
        return 1.0 - (distance / max_distance)


_performance_monitor = PerformanceMonitor()
_batch_processor = BatchProcessor()
_adaptive_processing = AdaptiveProcessing()
_face_quality_scorer = FaceQualityScorer()


def get_performance_monitor() -> PerformanceMonitor:
    return _performance_monitor


def get_batch_processor() -> BatchProcessor:
    return _batch_processor


def get_adaptive_processing() -> AdaptiveProcessing:
    return _adaptive_processing


def get_face_quality_scorer() -> FaceQualityScorer:
    return _face_quality_scorer
