"""
AdaFace Face Recognition Service

AdaFace uses adaptive margin to handle image quality variation,
achieving superior accuracy on low-quality surveillance images.

Supports:
- ONNX model loading for inference
- Quality-adaptive embedding extraction (512-D)
- Benchmark comparison against ArcFace baseline
- Model promotion via runtime registry
"""

import logging
import os
import time
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from onnx_providers import runtime_providers

logger = logging.getLogger(__name__)

try:
    import onnxruntime as ort
    HAS_ORT = True
except ImportError:
    HAS_ORT = False

ADAFACE_MODEL_PATH = os.getenv(
    "ADAFACE_MODEL_PATH", "models/adaface.onnx"
)
ADAFACE_INPUT_SIZE = int(os.getenv("ADAFACE_INPUT_SIZE", "112"))
ADAFACE_EMBEDDING_DIM = 512


class AdaFaceService:
    """AdaFace face recognition with quality-adaptive margin."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or ADAFACE_MODEL_PATH
        self.input_size = ADAFACE_INPUT_SIZE
        self.embedding_dim = ADAFACE_EMBEDDING_DIM
        self.session: Optional["ort.InferenceSession"] = None
        self._loaded = False

    def load_model(self) -> bool:
        """Load AdaFace ONNX model. Returns True only if model or simulation mode is ready."""
        if self._loaded:
            return self.session is not None or not os.path.exists(self.model_path) or not HAS_ORT

        if not os.path.exists(self.model_path):
            logger.warning(
                "AdaFace model not found at %s; running in simulation mode",
                self.model_path,
            )
            self._loaded = True
            return True  # simulation mode is valid

        if not HAS_ORT:
            logger.warning("onnxruntime not installed; AdaFace runs in simulation mode")
            self._loaded = True
            return True  # simulation mode is valid

        try:
            providers_env = os.getenv("ADAFACE_PROVIDERS", "").strip()
            providers = (
                [item.strip() for item in providers_env.split(",") if item.strip()]
                if providers_env
                else runtime_providers(ort, logger)
            )
            self.session = ort.InferenceSession(self.model_path, providers=providers)
            self._loaded = True
            logger.info(
                "AdaFace model loaded from %s (%s)",
                self.model_path,
                self.session.get_providers(),
            )
            return True
        except Exception as e:
            logger.error("Failed to load AdaFace model: %s; falling back to simulation mode", e)
            self._loaded = True  # mark loaded so we don't retry; session stays None → simulation
            return False  # caller knows the real model failed

    def _preprocess(self, face_img: np.ndarray) -> np.ndarray:
        """Preprocess face image for AdaFace input.

        - Resize to input_size x input_size
        - Normalize to [-1, 1]
        - Transpose to NCHW format
        """
        if face_img is None or face_img.size == 0:
            raise ValueError("Empty face image")

        if len(face_img.shape) == 2:
            face_img = cv2.cvtColor(face_img, cv2.COLOR_GRAY2BGR)

        resized = cv2.resize(face_img, (self.input_size, self.input_size))
        normalized = (resized.astype(np.float32) - 127.5) / 127.5
        transposed = np.transpose(normalized, (2, 0, 1))  # HWC -> CHW
        return np.expand_dims(transposed, axis=0)  # Add batch dim

    def _estimate_quality(self, face_img: np.ndarray) -> float:
        """Estimate face image quality score (0-1).

        Uses Laplacian variance as a blur/quality proxy.
        AdaFace uses this score to adaptively adjust the margin.
        """
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY) if len(face_img.shape) == 3 else face_img
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        quality = min(1.0, laplacian_var / 500.0)
        return float(quality)

    def _fallback_embedding(self, face_img: np.ndarray) -> np.ndarray:
        """Generate deterministic embedding when ONNX model is not available."""
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY) if len(face_img.shape) == 3 else face_img
        resized = cv2.resize(gray, (32, 16)).astype(np.float32)
        flat = resized.flatten()  # 512 values
        norm = np.linalg.norm(flat)
        if norm == 0:
            return np.zeros(self.embedding_dim, dtype=np.float32)
        vec = flat / norm
        if len(vec) < self.embedding_dim:
            vec = np.concatenate([vec, np.zeros(self.embedding_dim - len(vec))])
        return vec[: self.embedding_dim].astype(np.float32)

    def extract_embedding(
        self, face_img: np.ndarray
    ) -> Tuple[np.ndarray, float, float]:
        """Extract AdaFace embedding from a face crop.

        Returns:
            (embedding, quality_score, inference_time_ms)
        """
        if not self._loaded:
            self.load_model()

        quality = self._estimate_quality(face_img)

        if self.session is not None:
            try:
                input_tensor = self._preprocess(face_img)
                input_name = self.session.get_inputs()[0].name

                start = time.perf_counter()
                outputs = self.session.run(None, {input_name: input_tensor})
                elapsed_ms = (time.perf_counter() - start) * 1000

                embedding = outputs[0].flatten()
                embedding = embedding / np.linalg.norm(embedding)
                return embedding, quality, elapsed_ms

            except Exception as e:
                logger.warning("AdaFace ONNX inference failed, using fallback: %s", e)

        start = time.perf_counter()
        embedding = self._fallback_embedding(face_img)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return embedding, quality, elapsed_ms

    def compare_embeddings(
        self, emb1: np.ndarray, emb2: np.ndarray
    ) -> Dict[str, float]:
        """Compare two AdaFace embeddings using cosine similarity."""
        v1 = np.asarray(emb1, dtype=np.float32)
        v2 = np.asarray(emb2, dtype=np.float32)

        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 == 0 or n2 == 0:
            return {"cosine_similarity": 0.0, "distance": 1.0, "match": False}

        cosine_sim = float(np.dot(v1, v2) / (n1 * n2))
        distance = 1.0 - cosine_sim
        threshold = 0.4

        return {
            "cosine_similarity": round(cosine_sim, 6),
            "distance": round(distance, 6),
            "threshold": threshold,
            "match": distance < threshold,
        }

    def benchmark(
        self,
        test_images: List[np.ndarray],
        arcface_embeddings: Optional[List[np.ndarray]] = None,
    ) -> Dict:
        """Benchmark AdaFace against ArcFace on test images.

        Returns performance metrics and comparison if ArcFace embeddings provided.
        """
        if not self._loaded:
            self.load_model()

        latencies = []
        qualities = []
        embeddings = []

        for img in test_images:
            emb, quality, latency_ms = self.extract_embedding(img)
            embeddings.append(emb)
            qualities.append(quality)
            latencies.append(latency_ms)

        results = {
            "model": "AdaFace",
            "num_images": len(test_images),
            "embedding_dim": self.embedding_dim,
            "latency_mean_ms": round(float(np.mean(latencies)), 2) if latencies else 0,
            "latency_p95_ms": round(float(np.percentile(latencies, 95)), 2) if latencies else 0,
            "quality_mean": round(float(np.mean(qualities)), 4) if qualities else 0,
            "quality_min": round(float(np.min(qualities)), 4) if qualities else 0,
            "has_onnx_model": self.session is not None,
        }

        if arcface_embeddings and len(arcface_embeddings) == len(embeddings):
            similarities = []
            for ada_emb, arc_emb in zip(embeddings, arcface_embeddings):
                ada_n = ada_emb / max(np.linalg.norm(ada_emb), 1e-8)
                arc_n = np.asarray(arc_emb, dtype=np.float32)
                arc_n = arc_n / max(np.linalg.norm(arc_n), 1e-8)
                sim = float(np.dot(ada_n, arc_n))
                similarities.append(sim)

            results["arcface_comparison"] = {
                "cross_model_similarity_mean": round(float(np.mean(similarities)), 4),
                "cross_model_similarity_std": round(float(np.std(similarities)), 4),
            }

        return results

    def get_status(self) -> Dict:
        """Get current AdaFace service status."""
        return {
            "model": "AdaFace",
            "model_path": self.model_path,
            "model_exists": os.path.exists(self.model_path),
            "onnx_loaded": self.session is not None,
            "fallback_mode": self.session is None,
            "embedding_dim": self.embedding_dim,
            "input_size": self.input_size,
        }


# Singleton instance
adaface_service = AdaFaceService()
