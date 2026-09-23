"""
Continual Learning Module for Face Recognition
Allows adding new faces incrementally without full retraining.

Persistence: the buffer is automatically loaded from disk at startup and
flushed to disk on:
  - Process SIGTERM / SIGINT (graceful shutdown)
  - Every CONTINUAL_LEARNING_FLUSH_INTERVAL_SAMPLES new samples (default 50)
  - Explicit call to export_buffer()

Set CONTINUAL_LEARNING_BUFFER_PATH env var to override the default flush file.
"""

import atexit
import logging
import signal
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import json
import os

logger = logging.getLogger(__name__)

_DEFAULT_BUFFER_PATH = os.getenv(
    "CONTINUAL_LEARNING_BUFFER_PATH",
    os.path.join(os.path.dirname(__file__), "..", "backend", "data", "continual_learning_buffer.json"),
)
_FLUSH_INTERVAL = int(os.getenv("CONTINUAL_LEARNING_FLUSH_INTERVAL_SAMPLES", "50"))


@dataclass
class LearningRecord:
    """Record of learning updates"""
    visitor_id: str
    embedding: np.ndarray
    confidence: float
    source: str  # 'manual', 'auto', 'verification'
    timestamp: str
    verified: bool = False


class ContinualLearning:
    """Continual learning for incremental face recognition updates.

    The in-memory buffer is automatically persisted to ``buffer_path`` so that
    learning signals survive process restarts. SIGTERM / SIGINT and Python's
    ``atexit`` hook all trigger a flush.
    """

    def __init__(
        self,
        memory_size: int = 1000,
        min_confidence: float = 0.7,
        buffer_path: Optional[str] = None,
    ):
        self.memory_size = memory_size
        self.min_confidence = min_confidence
        self.learning_buffer: List[LearningRecord] = []
        self.embedding_stats: Dict[str, Dict] = {}
        self._buffer_path: str = buffer_path or _DEFAULT_BUFFER_PATH
        self._samples_since_flush: int = 0

        # Load persisted buffer from previous run
        self._load_on_startup()

        # Register graceful-shutdown hooks
        atexit.register(self._flush_on_exit)
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._signal_handler)
            except (OSError, ValueError):
                # Signal handling may fail in non-main threads; skip silently.
                pass

    def _signal_handler(self, signum: int, frame) -> None:
        logger.info("ContinualLearning received signal %s — flushing buffer.", signum)
        self._flush_on_exit()
        # Re-raise default so the process actually exits.
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    def _flush_on_exit(self) -> None:
        if self.learning_buffer or self.embedding_stats:
            self.export_buffer(self._buffer_path)

    def _load_on_startup(self) -> None:
        if os.path.exists(self._buffer_path):
            ok = self.import_buffer(self._buffer_path)
            if ok:
                logger.info(
                    "ContinualLearning buffer restored from %s (%d records).",
                    self._buffer_path,
                    len(self.learning_buffer),
                )
    
    def add_sample(self, visitor_id: str, embedding: np.ndarray, 
                   confidence: float, source: str = 'auto') -> bool:
        """Add a new sample to the learning buffer"""
        
        if confidence < self.min_confidence:
            return False
        
        record = LearningRecord(
            visitor_id=visitor_id,
            embedding=embedding.copy(),
            confidence=confidence,
            source=source,
            timestamp=datetime.now().isoformat(),
            verified=(source == 'manual')
        )
        
        self.learning_buffer.append(record)

        if len(self.learning_buffer) > self.memory_size:
            self._prune_buffer()

        self._update_stats(visitor_id, embedding, confidence)

        # Periodic flush to avoid data loss on unexpected process exit
        self._samples_since_flush += 1
        if self._samples_since_flush >= _FLUSH_INTERVAL:
            self._samples_since_flush = 0
            try:
                self.export_buffer(self._buffer_path)
            except Exception as exc:
                logger.warning("Periodic continual-learning flush failed: %s", exc)

        return True
    
    def _prune_buffer(self):
        """Remove lowest confidence samples when buffer is full"""
        if not self.learning_buffer:
            return
        
        sorted_buffer = sorted(self.learning_buffer, key=lambda x: x.confidence, reverse=True)
        self.learning_buffer = sorted_buffer[:self.memory_size]
    
    def _update_stats(self, visitor_id: str, embedding: np.ndarray, confidence: float):
        """Update running statistics for a visitor"""
        if visitor_id not in self.embedding_stats:
            self.embedding_stats[visitor_id] = {
                'count': 0,
                'mean_embedding': np.zeros_like(embedding),
                'sum_confidence': 0.0,
                'first_seen': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
            }
        
        stats = self.embedding_stats[visitor_id]
        n = stats['count']
        
        stats['mean_embedding'] = (stats['mean_embedding'] * n + embedding) / (n + 1)
        stats['count'] += 1
        stats['sum_confidence'] += confidence
        stats['last_seen'] = datetime.now().isoformat()
    
    def get_refined_embedding(self, visitor_id: str) -> Optional[np.ndarray]:
        """Get refined embedding using all stored samples"""
        if visitor_id not in self.embedding_stats:
            return None
        
        stats = self.embedding_stats[visitor_id]
        return stats['mean_embedding']
    
    def get_samples_for_verification(self, min_confidence: float = 0.5) -> List[Dict]:
        """Get samples that need manual verification"""
        unverified = [
            {
                'visitor_id': r.visitor_id,
                'embedding_norm': float(np.linalg.norm(r.embedding)),
                'confidence': r.confidence,
                'source': r.source,
                'timestamp': r.timestamp,
            }
            for r in self.learning_buffer
            if not r.verified and r.confidence >= min_confidence
        ]
        
        return unverified
    
    def verify_sample(self, visitor_id: str, embedding: np.ndarray, is_correct: bool):
        """Mark a sample as verified or rejected"""
        for record in self.learning_buffer:
            if record.visitor_id == visitor_id and np.allclose(record.embedding, embedding, atol=0.01):
                record.verified = is_correct
                break
    
    def get_learning_stats(self) -> Dict:
        """Get overall learning statistics"""
        total_samples = len(self.learning_buffer)
        verified_samples = sum(1 for r in self.learning_buffer if r.verified)
        unique_visitors = len(self.embedding_stats)
        
        avg_confidence = 0.0
        if total_samples > 0:
            avg_confidence = np.mean([r.confidence for r in self.learning_buffer])
        
        return {
            'total_samples': total_samples,
            'verified_samples': verified_samples,
            'unverified_samples': total_samples - verified_samples,
            'unique_visitors': unique_visitors,
            'average_confidence': float(avg_confidence),
            'memory_usage_percent': (total_samples / self.memory_size) * 100,
        }
    
    def should_trigger_retrain(self, threshold: float = 0.3) -> bool:
        """Check if enough new data accumulated to warrant retraining"""
        recent_threshold = datetime.now().timestamp() - (7 * 24 * 60 * 60)
        
        recent_samples = [
            r for r in self.learning_buffer
            if datetime.fromisoformat(r.timestamp).timestamp() > recent_threshold
        ]
        
        unique_recent = set(r.visitor_id for r in recent_samples)
        
        return len(unique_recent) >= threshold * 10
    
    def export_buffer(self, filepath: str) -> bool:
        """Export learning buffer to file"""
        try:
            data = {
                'learning_records': [
                    {
                        'visitor_id': r.visitor_id,
                        'embedding': r.embedding.tolist(),
                        'confidence': r.confidence,
                        'source': r.source,
                        'timestamp': r.timestamp,
                        'verified': r.verified,
                    }
                    for r in self.learning_buffer
                ],
                'embedding_stats': {
                    vid: {
                        **{k: v for k, v in vstats.items() if k != 'mean_embedding'},
                        'mean_embedding': vstats['mean_embedding'].tolist() if isinstance(vstats.get('mean_embedding'), np.ndarray) else vstats.get('mean_embedding', []),
                    }
                    for vid, vstats in self.embedding_stats.items()
                },
                'config': {
                    'memory_size': self.memory_size,
                    'min_confidence': self.min_confidence,
                }
            }
            
            with open(filepath, 'w') as f:
                json.dump(data, f)
            
            return True
        except Exception as e:
            print(f"Error exporting buffer: {e}")
            return False
    
    def import_buffer(self, filepath: str) -> bool:
        """Import learning buffer from file"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            self.learning_buffer = [
                LearningRecord(
                    visitor_id=r['visitor_id'],
                    embedding=np.array(r['embedding']),
                    confidence=r['confidence'],
                    source=r['source'],
                    timestamp=r['timestamp'],
                    verified=r.get('verified', False),
                )
                for r in data.get('learning_records', [])
            ]
            
            raw_stats = data.get('embedding_stats', {})
            self.embedding_stats = {
                vid: {
                    **{k: v for k, v in vstats.items() if k != 'mean_embedding'},
                    'mean_embedding': np.array(vstats['mean_embedding']) if 'mean_embedding' in vstats else np.array([]),
                }
                for vid, vstats in raw_stats.items()
            }
            
            return True
        except Exception as e:
            print(f"Error importing buffer: {e}")
            return False


class AdaptiveThreshold:
    """Adaptive confidence threshold based on data quality"""
    
    def __init__(self, base_threshold: float = 0.6):
        self.base_threshold = base_threshold
        self.adjustments: Dict[str, float] = {}
    
    def calculate_threshold(self, visitor_id: str, 
                          sample_count: int, 
                          avg_confidence: float) -> float:
        """Calculate adaptive threshold for a specific visitor"""
        
        threshold = self.base_threshold
        
        if sample_count > 10:
            threshold -= 0.05
        if sample_count > 50:
            threshold -= 0.05
        
        if avg_confidence > 0.85:
            threshold -= 0.05
        elif avg_confidence < 0.6:
            threshold += 0.1
        
        if visitor_id in self.adjustments:
            threshold += self.adjustments[visitor_id]
        
        return max(0.4, min(0.9, threshold))
    
    def adjust_for_visitor(self, visitor_id: str, adjustment: float):
        """Manually adjust threshold for a specific visitor"""
        self.adjustments[visitor_id] = adjustment


def get_continual_learning_config() -> dict:
    """Get default continual learning configuration"""
    return {
        "enabled": True,
        "memory_size": 1000,
        "min_confidence": 0.7,
        "auto_verify_manual": True,
        "retrain_threshold": 0.3,
        "retrain_min_samples": 10,
    }
