import os
import cv2
import numpy as np
from typing import List, Optional, Dict, Any
from runtime_registry import get_runtime_component

try:
    from deepface import DeepFace
    _DEEPFACE_AVAILABLE = True
except Exception:
    DeepFace = None
    _DEEPFACE_AVAILABLE = False

try:
    from adaface_service import adaface_service as _adaface
    _ADAFACE_AVAILABLE = True
except ImportError:
    _adaface = None
    _ADAFACE_AVAILABLE = False

try:
    # Primary ArcFace backend (ONNX/onnxruntime) — works without TensorFlow,
    # so it is the real recognition path on Python 3.13/3.14.
    from insightface_service import insightface_service as _insightface
    _INSIGHTFACE_AVAILABLE = True
except Exception:
    _insightface = None
    _INSIGHTFACE_AVAILABLE = False

try:
    from vit_engine import get_vit_service
    _VIT_AVAILABLE = True
except Exception:
    get_vit_service = None
    _VIT_AVAILABLE = False


class FaceEngine:
    def __init__(self, model_name=None, detector_backend=None):
        """
        Initialize FaceEngine.

        model_name: "VGG-Face", "Facenet", "OpenFace", "ArcFace", "AdaFace", "Dlib", "SFace"
        detector_backend: "opencv", "retinaface", "mtcnn", "ssd", "dlib", "mediapipe", "yolov8"
        """
        recognition_config = get_runtime_component("face_recognition")
        detector_config = get_runtime_component("face_detector")
        self.model_name = model_name or recognition_config.get("current_model", "ArcFace")
        self.detector_backend = detector_backend or detector_config.get("current_model", "opencv")
        model_norm = str(self.model_name).lower()
        self._use_adaface = model_norm == "adaface"
        self._use_custom_classifier = "custom" in model_norm
        self._use_ensemble = "ensemble" in model_norm
        self._use_vit = ("vit" in model_norm or "transformer" in model_norm) or self._use_ensemble
        self._fallback_face_cascade = self._load_fallback_face_cascade()
        # Warm up the model on first use
        self._warmed_up = False
        # Which backend produced the most recent embedding:
        # "arcface" | "adaface" | "vit" | "ensemble" | "deepface" | "fallback" | None
        self.last_embedding_engine: Optional[str] = None
        # Strict mode: when enabled, the weak pixel-similarity fallback embedding
        # is refused (returns None) instead of silently entering the gallery.
        # This prevents non-discriminative "identities" when no real ArcFace
        # backend is available. Recommended ON in production.
        self._strict_recognition = os.getenv(
            "SENTINELCV_STRICT_RECOGNITION", "0"
        ).strip().lower() in ("1", "true", "yes", "on")

    def _load_fallback_face_cascade(self):
        """Load a lightweight OpenCV cascade for face detection fallback."""
        try:
            cascade = cv2.CascadeClassifier(
                f"{cv2.data.haarcascades}haarcascade_frontalface_default.xml"
            )
            if cascade.empty():
                return None
            return cascade
        except Exception as e:
            print(f"Fallback face cascade load error: {e}")
            return None

    def _coerce_image(self, img_path_or_array) -> Optional[np.ndarray]:
        if isinstance(img_path_or_array, str):
            return cv2.imread(img_path_or_array)
        return img_path_or_array

    def _fallback_extract_faces(self, img: Optional[np.ndarray]) -> List[Dict[str, Any]]:
        """Detect faces with OpenCV when DeepFace is unavailable."""
        if (
            img is None
            or self._fallback_face_cascade is None
            or self._fallback_face_cascade.empty()
        ):
            return []

        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            detections = self._fallback_face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(48, 48),
            )
        except Exception as e:
            print(f"Fallback face extraction error: {e}")
            return []

        faces: List[Dict[str, Any]] = []
        for x, y, w, h in sorted(detections, key=lambda rect: rect[2] * rect[3], reverse=True):
            face_img = img[y : y + h, x : x + w]
            if face_img is None or face_img.size == 0:
                continue
            faces.append(
                {
                    "face": face_img,
                    "facial_area": {
                        "x": int(x),
                        "y": int(y),
                        "w": int(w),
                        "h": int(h),
                    },
                    "confidence": 0.55,
                }
            )
        return faces

    def _fallback_embedding(self, face_img: np.ndarray) -> Optional[List[float]]:
        """Generate a deterministic lightweight embedding when no real ArcFace backend is available.

        WARNING: this is a 32x32 grayscale pixel feature, NOT identity-discriminative
        face recognition. It exists only so dev/CI keeps working without the ONNX models.
        In strict mode it is refused so weak embeddings never enter the gallery.
        """
        if self._strict_recognition:
            print(
                "[FaceEngine] STRICT mode: refusing weak fallback embedding — "
                "real ArcFace (InsightFace/AdaFace) backend is not available."
            )
            return None
        try:
            if face_img is None or face_img.size == 0:
                return None
            gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY) if len(face_img.shape) == 3 else face_img
            resized = cv2.resize(gray, (32, 32)).astype(np.float32)
            flat = resized.flatten()
            norm = np.linalg.norm(flat)
            if norm == 0:
                return None
            vec = (flat / norm).tolist()
            # Match the expected 512-length embedding contract used by backend logic.
            if len(vec) < 512:
                vec = vec + [0.0] * (512 - len(vec))
            self.last_embedding_engine = "fallback"
            return vec[:512]
        except Exception as e:
            print(f"Fallback embedding error: {e}")
            return None

    def _warmup(self):
        """Pre-load models to avoid first-call latency."""
        if not self._warmed_up:
            if self._use_vit or self._use_ensemble:
                self._warmup_vit()
            # Prefer the InsightFace ArcFace (ONNX) backend — real recognition
            # without TensorFlow. Warm it so first-call latency is paid here.
            if (
                not self._use_adaface
                and _INSIGHTFACE_AVAILABLE
                and _insightface is not None
                and _insightface.available
            ):
                if self._get_insightface_embedding(np.zeros((112, 112, 3), dtype=np.uint8)) is not None or _insightface.available:
                    self._warmed_up = True
                    print("FaceEngine warmed up with InsightFace ArcFace (ONNX)")
                    return
            if not _DEEPFACE_AVAILABLE:
                print("FaceEngine running in fallback mode (no ArcFace backend available).")
                self._warmed_up = True
                return
            try:
                dummy = np.zeros((160, 160, 3), dtype=np.uint8)
                DeepFace.represent(
                    img_path=dummy,
                    model_name=self._resolve_deepface_model_name(),
                    detector_backend="skip",
                    enforce_detection=False,
                )
                self._warmed_up = True
                print(f"FaceEngine warmed up with {self.model_name}")
            except Exception as e:
                print(f"Warmup notice: {e}")
                self._warmed_up = True

    def _refresh_runtime_config(self) -> None:
        recognition_config = get_runtime_component("face_recognition")
        detector_config = get_runtime_component("face_detector")

        next_model = recognition_config.get("current_model", self.model_name)
        if next_model != self.model_name:
            self.model_name = next_model
            model_norm = str(self.model_name).lower()
            self._use_adaface = model_norm == "adaface"
            self._use_custom_classifier = "custom" in model_norm
            self._use_ensemble = "ensemble" in model_norm
            self._use_vit = ("vit" in model_norm or "transformer" in model_norm) or self._use_ensemble
            self._warmed_up = False

        next_detector = detector_config.get("current_model", self.detector_backend)
        if next_detector != self.detector_backend:
            self.detector_backend = next_detector

    def _warmup_vit(self) -> None:
        if not _VIT_AVAILABLE or get_vit_service is None:
            print("ViT backend not available; falling back to ArcFace")
            return
        try:
            service = get_vit_service()
            service.load_model()
        except Exception as e:
            print(f"ViT warmup notice: {e}")

    def _resolve_deepface_model_name(self) -> str:
        if self._use_custom_classifier or self._use_vit or self._use_ensemble:
            return "ArcFace"
        return self.model_name

    def _get_insightface_embedding(self, face_img) -> Optional[List[float]]:
        """Real 512-d ArcFace embedding via InsightFace (ONNX). None if unavailable."""
        if not _INSIGHTFACE_AVAILABLE or _insightface is None or not _insightface.available:
            return None
        try:
            emb = _insightface.extract_embedding(face_img)
            if emb is not None:
                self.last_embedding_engine = "arcface"
            return emb
        except Exception as e:
            print(f"InsightFace embedding error: {e}")
            return None

    def _get_vit_embedding(self, face_img) -> Optional[List[float]]:
        if not _VIT_AVAILABLE or get_vit_service is None:
            return None
        try:
            service = get_vit_service()
            return service.extract_embedding(face_img, normalize=True, output_dim=512)
        except Exception as e:
            print(f"ViT embedding error: {e}")
            return None

    def _combine_embeddings(
        self,
        arcface_embedding: Optional[List[float]],
        vit_embedding: Optional[List[float]],
    ) -> Optional[List[float]]:
        if arcface_embedding and vit_embedding:
            min_dim = min(len(arcface_embedding), len(vit_embedding))
            a = np.array(arcface_embedding[:min_dim], dtype=np.float32)
            b = np.array(vit_embedding[:min_dim], dtype=np.float32)
            combined = (a + b) / 2.0
            norm = np.linalg.norm(combined)
            if norm > 0:
                combined = combined / norm
            return combined.tolist()
        return arcface_embedding or vit_embedding

    def extract_face(self, img_path_or_array) -> List[Dict[str, Any]]:
        """
        Extract faces from the image.
        Returns list of dicts with 'face' (numpy array) and 'facial_area' region.
        """
        self._warmup()
        img = self._coerce_image(img_path_or_array)

        # Primary: RetinaFace via InsightFace — the strong detector that is already
        # loaded for embeddings. Gives real det_score confidence + 5 landmarks for
        # alignment, and catches profile/small/low-light faces Haar misses.
        if (
            not self._use_adaface
            and _INSIGHTFACE_AVAILABLE
            and _insightface is not None
            and _insightface.available
        ):
            try:
                faces = _insightface.detect_faces(img if img is not None else img_path_or_array)
                if faces:
                    return faces
            except Exception as e:
                print(f"InsightFace detect error, falling back: {e}")

        # Secondary: DeepFace (only if installed).
        if _DEEPFACE_AVAILABLE:
            try:
                return DeepFace.extract_faces(
                    img_path=img_path_or_array,
                    detector_backend=self.detector_backend,
                    enforce_detection=False,
                )
            except Exception as e:
                print(f"Error extracting faces: {e}")

        # Last resort: OpenCV Haar cascade.
        return self._fallback_extract_faces(img)

    def get_embedding(self, face_img) -> Optional[List[float]]:
        """
        Generate 512-dim face embedding using configured model (ArcFace or AdaFace).
        """
        self._refresh_runtime_config()
        self._warmup()
        vit_embedding = None
        if self._use_vit or self._use_ensemble:
            vit_embedding = self._get_vit_embedding(face_img)
            if self._use_vit and not self._use_ensemble and vit_embedding is not None:
                return vit_embedding

        arcface_embedding = None
        if self._use_adaface and _ADAFACE_AVAILABLE and _adaface is not None:
            try:
                if isinstance(face_img, str):
                    img = cv2.imread(face_img)
                    if img is None:
                        return None
                else:
                    img = face_img
                emb, _quality, _latency = _adaface.extract_embedding(img)
                arcface_embedding = emb.tolist()
                self.last_embedding_engine = "adaface"
            except Exception as e:
                print(f"AdaFace embedding error, falling back: {e}")

        # Real ArcFace via InsightFace (ONNX) — primary path when AdaFace not selected.
        if arcface_embedding is None:
            arcface_embedding = self._get_insightface_embedding(face_img)

        if arcface_embedding is None:
            if not _DEEPFACE_AVAILABLE:
                if isinstance(face_img, str):
                    img = cv2.imread(face_img)
                    arcface_embedding = self._fallback_embedding(img) if img is not None else None
                else:
                    arcface_embedding = self._fallback_embedding(face_img)
            else:
                try:
                    deepface_model = self._resolve_deepface_model_name()
                    embedding_objs = DeepFace.represent(
                        img_path=face_img,
                        model_name=deepface_model,
                        detector_backend=self.detector_backend,
                        enforce_detection=False,
                    )
                    if embedding_objs:
                        arcface_embedding = embedding_objs[0]["embedding"]
                except Exception as e:
                    print(f"Error generating embedding: {e}")

        if self._use_ensemble:
            result = self._combine_embeddings(arcface_embedding, vit_embedding)
        elif self._use_vit:
            result = vit_embedding or arcface_embedding
        else:
            result = arcface_embedding
        return self._validate_embedding(result)

    def _validate_embedding(self, embedding) -> Optional[List[float]]:
        """Discard embeddings with NaN/Inf or near-zero norm."""
        if embedding is None:
            return None
        arr = np.array(embedding, dtype=np.float32)
        if not np.all(np.isfinite(arr)):
            print("[FaceEngine] Embedding contains NaN/Inf — discarding")
            return None
        if np.linalg.norm(arr) < 1e-8:
            print("[FaceEngine] Embedding has near-zero norm — discarding")
            return None
        return embedding

    def get_embedding_from_crop(self, face_crop: np.ndarray) -> Optional[List[float]]:
        """
        Generate embedding from an already-cropped face image.
        Skips face detection since we already have the face.
        """
        self._refresh_runtime_config()
        self._warmup()

        vit_embedding = None
        if self._use_vit or self._use_ensemble:
            vit_embedding = self._get_vit_embedding(face_crop)
            if self._use_vit and not self._use_ensemble and vit_embedding is not None:
                return vit_embedding

        arcface_embedding = None
        if self._use_adaface and _ADAFACE_AVAILABLE and _adaface is not None:
            try:
                emb, _q, _l = _adaface.extract_embedding(face_crop)
                arcface_embedding = emb.tolist()
                self.last_embedding_engine = "adaface"
            except Exception as e:
                print(f"AdaFace crop embedding error, falling back: {e}")

        # Real ArcFace via InsightFace (ONNX) — primary path when AdaFace not selected.
        if arcface_embedding is None:
            arcface_embedding = self._get_insightface_embedding(face_crop)

        if arcface_embedding is None:
            if not _DEEPFACE_AVAILABLE:
                arcface_embedding = self._fallback_embedding(face_crop)
            else:
                try:
                    if face_crop.shape[0] < 10 or face_crop.shape[1] < 10:
                        return None
                    face_resized = cv2.resize(face_crop, (160, 160))
                    deepface_model = self._resolve_deepface_model_name()
                    embedding_objs = DeepFace.represent(
                        img_path=face_resized,
                        model_name=deepface_model,
                        detector_backend="skip",
                        enforce_detection=False,
                    )
                    if embedding_objs:
                        arcface_embedding = embedding_objs[0]["embedding"]
                except Exception as e:
                    print(f"Error generating embedding from crop: {e}")

        if self._use_ensemble:
            result = self._combine_embeddings(arcface_embedding, vit_embedding)
        elif self._use_vit:
            result = vit_embedding or arcface_embedding
        else:
            result = arcface_embedding
        return self._validate_embedding(result)

    def verify_faces(self, img1, img2) -> Optional[Dict[str, Any]]:
        """Verify if two face images belong to the same person."""
        self._warmup()
        if not _DEEPFACE_AVAILABLE:
            emb1 = self.get_embedding(img1)
            emb2 = self.get_embedding(img2)
            if not emb1 or not emb2:
                return None
            v1 = np.array(emb1, dtype=np.float32)
            v2 = np.array(emb2, dtype=np.float32)
            denom = (np.linalg.norm(v1) * np.linalg.norm(v2))
            distance = 1.0 if denom == 0 else float(1.0 - np.dot(v1, v2) / denom)
            threshold = float(os.getenv("FACE_VERIFY_THRESHOLD", "0.4"))
            return {
                "verified": distance < threshold,
                "distance": distance,
                "threshold": threshold,
                "model": "fallback",
            }
        try:
            result = DeepFace.verify(
                img1_path=img1,
                img2_path=img2,
                model_name=self._resolve_deepface_model_name(),
                detector_backend=self.detector_backend,
            )
            return result
        except Exception as e:
            print(f"Error verifying faces: {e}")
            return None


    def engine_status(self) -> Dict[str, Any]:
        """Report which recognition backend is active and whether it is real.

        `degraded` is True when no real ArcFace backend (InsightFace/AdaFace) is
        available — meaning identification would rely on the weak pixel fallback
        (or be refused entirely in strict mode).
        """
        status = recognition_backend_status()
        status["last_embedding_engine"] = self.last_embedding_engine
        status["strict_recognition"] = self._strict_recognition
        status["selected_model"] = self.model_name
        return status


def recognition_backend_status() -> Dict[str, Any]:
    """Module-level view of which real recognition backends are loadable.

    Safe to call without an embedding having been produced — it reports
    availability, so /health can answer "can this box really identify a face?".
    """
    insightface_available = bool(
        _INSIGHTFACE_AVAILABLE and _insightface is not None and getattr(_insightface, "available", False)
    )
    adaface_available = bool(_ADAFACE_AVAILABLE and _adaface is not None)
    real_recognition = insightface_available or adaface_available
    return {
        "real_recognition": real_recognition,
        "degraded": not real_recognition,
        "backends": {
            "insightface_arcface": insightface_available,
            "adaface": adaface_available,
            "vit": bool(_VIT_AVAILABLE),
            "deepface": bool(_DEEPFACE_AVAILABLE),
        },
    }


if __name__ == "__main__":
    engine = FaceEngine()
    engine._warmup()
    print("FaceEngine ready.")
    print("Recognition backend status:", engine.engine_status())
