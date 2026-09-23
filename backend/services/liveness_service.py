"""
S29: Liveness Detection & Anti-Spoofing Service (US-FUT-042)

Implements three detection methods:
1. Texture-based (LBP - Local Binary Patterns)
2. Motion-based (optical flow, eye blink detection)
3. Deep Learning-based (pre-trained CNN)

These can be used individually or in an ensemble for robust spoofing detection.
"""

import cv2
import numpy as np
import math
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from datetime import datetime
import logging
from pathlib import Path
import sys

from models.models import LivenessScore, LivenessChallenge, VisitorLog
from schemas.schemas import (
    LivenessScoreCreateRequest,
    LivenessDetectionResult,
    LivenessStatistics,
    LivenessConfig,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.liveness_core import LivenessCore

try:
    import mediapipe as mp
    from shared.mediapipe_compat import ensure_legacy_solutions
    MEDIAPIPE_AVAILABLE = ensure_legacy_solutions()
except ImportError:
    MEDIAPIPE_AVAILABLE = False

logger = logging.getLogger(__name__)


class LivenessDetectionService:
    """Unified service for liveness detection and anti-spoofing."""

    def __init__(self, config: Optional[LivenessConfig] = None):
        """Initialize service with optional configuration."""
        self.config = config or LivenessConfig()
        self._core = LivenessCore()
        self.lbp_cascade = None
        self.face_cascade = None
        self.eye_cascade = None
        self.eye_cascade_alt = None
        self.smile_cascade = None
        self.face_mesh = None
        self.pose = None
        self.hands = None
        self._load_cascades()
        self._load_mediapipe()

    def _load_mediapipe(self):
        """Load MediaPipe models for facial landmarks and pose estimation."""
        if not MEDIAPIPE_AVAILABLE:
            logger.warning("MediaPipe not available; using fallback detection methods")
            return
        
        try:
            mp_face_mesh = mp.solutions.face_mesh
            self.face_mesh = mp_face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
            )
            mp_pose = mp.solutions.pose
            self.pose = mp_pose.Pose(
                static_image_mode=False,
                model_complexity=1,
                smooth_landmarks=True,
                min_detection_confidence=0.5,
            )
            logger.info("MediaPipe models loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load MediaPipe models: {e}")
            self.face_mesh = None
            self.pose = None

    def _load_cascades(self):
        """Load Haar Cascades for face detection (fallback for LBP)."""
        cascade_path = cv2.data.haarcascades
        try:
            self.face_cascade = cv2.CascadeClassifier(
                f"{cascade_path}haarcascade_frontalface_default.xml"
            )
            self.eye_cascade = cv2.CascadeClassifier(
                f"{cascade_path}haarcascade_eye_tree_eyeglasses.xml"
            )
            self.eye_cascade_alt = cv2.CascadeClassifier(
                f"{cascade_path}haarcascade_eye.xml"
            )
            self.smile_cascade = cv2.CascadeClassifier(
                f"{cascade_path}haarcascade_smile.xml"
            )
        except Exception as e:
            logger.warning(f"Failed to load face cascade: {e}")

    def _detect_primary_face(self, gray_frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """Return the largest detected face bounding box in the frame."""
        if (
            self.face_cascade is None
            or self.face_cascade.empty()
            or gray_frame is None
            or gray_frame.size == 0
        ):
            return None

        try:
            faces = self.face_cascade.detectMultiScale(
                gray_frame,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(48, 48),
            )
        except Exception as exc:
            logger.debug("Face detection failed during fallback liveness analysis: %s", exc)
            return None

        if faces is None or len(faces) == 0:
            return None

        x, y, w, h = max(faces, key=lambda rect: rect[2] * rect[3])
        return int(x), int(y), int(w), int(h)

    def _prepare_roi_variants(
        self,
        gray_roi: np.ndarray,
        *,
        upscale_small: bool = False,
    ) -> List[np.ndarray]:
        """Build a small set of contrast-enhanced ROI variants for Haar fallback detectors."""
        if gray_roi is None or gray_roi.size == 0:
            return []

        variants: List[np.ndarray] = [gray_roi]

        try:
            equalized = cv2.equalizeHist(gray_roi)
            if equalized.size != 0 and not np.array_equal(equalized, gray_roi):
                variants.append(equalized)
        except Exception as exc:
            logger.debug("ROI equalization failed during fallback preprocessing: %s", exc)

        if upscale_small and min(gray_roi.shape[:2]) < 96:
            base_variants = list(variants)
            for roi in base_variants:
                try:
                    scaled = cv2.resize(
                        roi,
                        None,
                        fx=2.0,
                        fy=2.0,
                        interpolation=cv2.INTER_CUBIC,
                    )
                except Exception as exc:
                    logger.debug("ROI upscale failed during fallback preprocessing: %s", exc)
                    continue

                if scaled.size != 0:
                    variants.append(scaled)

        return variants

    def _detect_eye_counts(self, gray_frames: List[np.ndarray]) -> List[int]:
        """Estimate how many eyes are visible in each frame using Haar cascades."""
        eye_counts: List[int] = []
        cascades = [
            cascade
            for cascade in (self.eye_cascade, self.eye_cascade_alt)
            if cascade is not None and not cascade.empty()
        ]
        if not cascades:
            return eye_counts

        for gray in gray_frames:
            face = self._detect_primary_face(gray)
            if face is None:
                eye_counts.append(0)
                continue

            x, y, w, h = face
            face_roi = gray[y : y + h, x : x + w]
            upper_face = face_roi[: max(1, h // 2), :]
            if upper_face.size == 0:
                eye_counts.append(0)
                continue

            try:
                roi_variants = self._prepare_roi_variants(upper_face, upscale_small=True)
                max_detected_eyes = 0

                for cascade_index, cascade in enumerate(cascades):
                    for roi in roi_variants:
                        roi_height, roi_width = roi.shape[:2]
                        eyes = cascade.detectMultiScale(
                            roi,
                            scaleFactor=1.1 if cascade_index == 0 else 1.05,
                            minNeighbors=4 if cascade_index == 0 else 3,
                            minSize=(max(10, roi_width // 14), max(8, roi_height // 10)),
                        )
                        max_detected_eyes = max(max_detected_eyes, min(2, int(len(eyes))))
                        if max_detected_eyes >= 2:
                            break
                    if max_detected_eyes >= 2:
                        break

                eye_counts.append(max_detected_eyes)
            except Exception as exc:
                logger.debug("Eye detection failed during blink fallback: %s", exc)
                eye_counts.append(0)

        return eye_counts

    def _detect_smile_scores(self, gray_frames: List[np.ndarray]) -> List[float]:
        """Estimate smile presence per frame using face and smile cascades."""
        smile_scores: List[float] = []
        if self.smile_cascade is None or self.smile_cascade.empty():
            return smile_scores

        for gray in gray_frames:
            face = self._detect_primary_face(gray)
            if face is None:
                smile_scores.append(0.0)
                continue

            x, y, w, h = face
            face_roi = gray[y : y + h, x : x + w]
            mouth_margin = max(1, w // 8)
            mouth_top = max(0, (h // 2) - max(1, h // 10))
            lower_face = face_roi[mouth_top:, mouth_margin : max(mouth_margin + 1, w - mouth_margin)]
            if lower_face.size == 0:
                smile_scores.append(0.0)
                continue

            try:
                smile_area_ratio = 0.0
                roi_variants = self._prepare_roi_variants(lower_face)

                for variant_index, roi in enumerate(roi_variants):
                    roi_height, roi_width = roi.shape[:2]
                    smiles = self.smile_cascade.detectMultiScale(
                        roi,
                        scaleFactor=1.5 if variant_index == 0 else 1.2,
                        minNeighbors=18 if variant_index == 0 else 9,
                        minSize=(max(18, roi_width // 7), max(10, roi_height // 6)),
                    )

                    if smiles is None or len(smiles) == 0:
                        continue

                    largest_smile = max(smiles, key=lambda rect: rect[2] * rect[3])
                    _, _, sw, sh = largest_smile
                    face_area = max(1, w * h)
                    smile_area_ratio = max(smile_area_ratio, float((sw * sh) / face_area))

                smile_scores.append(smile_area_ratio)
            except Exception as exc:
                logger.debug("Smile detection failed during fallback analysis: %s", exc)
                smile_scores.append(0.0)
                continue

        return smile_scores

    def _track_face_motion(self, gray_frames: List[np.ndarray]) -> List[Tuple[float, float, float]]:
        """Track primary face center/width across frames for fallback motion checks."""
        track: List[Tuple[float, float, float]] = []
        for gray in gray_frames:
            face = self._detect_primary_face(gray)
            if face is None:
                continue

            x, y, w, h = face
            track.append((float(x + (w / 2.0)), float(y + (h / 2.0)), float(w)))

        return track

    def _normalize_score(self, score: Any, fallback: float = 0.5) -> float:
        """Coerce detector outputs into a bounded numeric confidence score."""
        try:
            normalized = float(score)
        except (TypeError, ValueError):
            logger.warning("Invalid liveness score %r received; using fallback %.2f", score, fallback)
            return fallback

        if not math.isfinite(normalized):
            logger.warning("Non-finite liveness score %r received; using fallback %.2f", score, fallback)
            return fallback

        return max(0.0, min(1.0, normalized))

    def _normalize_frame_sizes(self, frames: List[np.ndarray]) -> List[np.ndarray]:
        """Resize frames to a common size so temporal algorithms can compare them safely."""
        return self._core.normalize_frame_sizes(frames)

    def detect_liveness_texture_based(
        self, frame: np.ndarray
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Texture-based liveness detection using Local Binary Patterns (LBP).
        
        Real faces have natural skin texture variation (entropy).
        Printed/displayed photos have consistent flat patterns.
        
        Returns:
            (score, details) where score is 0.0-1.0 (higher = more likely real)
        """
        try:
            return self._core.texture_score(frame)
        except Exception as e:
            logger.error(f"Texture-based detection failed: {e}")
            return 0.5, {"error": str(e)}

    def detect_liveness_motion_based(
        self, frames: List[np.ndarray], fps: int = 30
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Motion-based liveness detection using optical flow and eye blink.
        
        Real faces produce natural motion (blinks, head movement).
        Static photos/replays show no motion.
        
        Args:
            frames: List of consecutive frames (video)
            fps: Frames per second of video
            
        Returns:
            (score, details) where score is 0.0-1.0
        """
        try:
            normalized_frames = self._normalize_frame_sizes(frames)
            gray_frames = [self._to_grayscale_uint8(f) for f in normalized_frames]
            eye_counts = self._detect_eye_counts(gray_frames)
            return self._core.motion_score(
                normalized_frames,
                fps=fps,
                eye_counts=eye_counts if eye_counts else None,
            )
        except Exception as e:
            logger.error(f"Motion-based detection failed: {e}")
            return 0.5, {"error": str(e)}

    def detect_liveness_deep_learning(
        self, frame: np.ndarray
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Deep Learning / Frequency-domain liveness detection.

        Uses a multi-signal approach combining:
        1. DCT (Discrete Cosine Transform) spectral analysis — real faces have
           richer high-frequency content than printed/screen-displayed photos.
        2. Color space analysis — printed photos and screens produce
           different chrominance distributions vs live skin.
        3. Moiré pattern detection — screens produce characteristic
           periodic patterns detectable via FFT.
        4. ONNX CNN model — if a pretrained liveness model is available at
           ``models/liveness_net.onnx``, it is used as the primary signal.

        Returns:
            (score, details) where score is 0.0–1.0 (higher = more likely real)
        """
        try:
            return self._core.spectral_score(frame)
        except Exception as e:
            logger.error(f"Deep learning detection failed: {e}")
            return 0.5, {"error": str(e)}

    def ensemble_detection(
        self,
        frame: Optional[np.ndarray] = None,
        frames: Optional[List[np.ndarray]] = None,
        methods: Optional[List[str]] = None,
    ) -> LivenessDetectionResult:
        """
        Ensemble detection combining multiple methods for robust liveness.
        
        Args:
            frame: Single frame (for texture/DL detection)
            frames: Video frames (for motion detection)
            methods: Which methods to use. Default: all enabled in config
            
        Returns:
            LivenessDetectionResult with final decision and details
        """
        if methods is None:
            methods = []
            if self.config.texture_enabled:
                methods.append("texture")
            if self.config.motion_enabled:
                methods.append("motion")
            if self.config.deep_learning_enabled:
                methods.append("deep_learning")

        scores = {}
        details = {}

        # Texture-based detection
        if "texture" in methods and frame is not None:
            try:
                texture_score, texture_details = self.detect_liveness_texture_based(frame)
                scores["texture"] = self._normalize_score(texture_score)
                details["texture"] = texture_details
            except Exception as e:
                logger.error(f"Texture detection error: {e}")
                scores["texture"] = 0.5

        # Motion-based detection
        if "motion" in methods and frames is not None and len(frames) > 1:
            try:
                motion_score, motion_details = self.detect_liveness_motion_based(frames)
                scores["motion"] = self._normalize_score(motion_score)
                details["motion"] = motion_details
            except Exception as e:
                logger.error(f"Motion detection error: {e}")
                scores["motion"] = 0.5

        # Deep learning-based detection
        if "deep_learning" in methods and frame is not None:
            try:
                dl_score, dl_details = self.detect_liveness_deep_learning(frame)
                scores["deep_learning"] = self._normalize_score(dl_score)
                details["deep_learning"] = dl_details
            except Exception as e:
                logger.error(f"Deep learning detection error: {e}")
                scores["deep_learning"] = 0.5

        # Ensemble combination
        if not scores:
            return LivenessDetectionResult(
                is_live=False,
                score=0.0,
                method="ensemble",
                details={"error": "No methods available"},
                quality_metrics={},
                attack_detected=True,
                attack_type="no_detection",
            )

        # Combine scores based on ensemble method
        if self.config.ensemble_method == "average":
            ensemble_score = sum(scores.values()) / len(scores)
        elif self.config.ensemble_method == "weighted":
            # Weight: texture=30%, motion=40%, DL=30%
            weighted_score = (
                scores.get("texture", 0.5) * 0.3 +
                scores.get("motion", 0.5) * 0.4 +
                scores.get("deep_learning", 0.5) * 0.3
            )
            ensemble_score = weighted_score
        else:  # voting
            threshold = self.config.overall_confidence_threshold
            live_votes = sum(1 for s in scores.values() if s >= threshold)
            ensemble_score = live_votes / len(scores)

        ensemble_score = self._normalize_score(ensemble_score, fallback=0.0)

        # Determine if live or spoof
        is_live = ensemble_score >= self.config.overall_confidence_threshold

        # Detect spoofing attacks
        attack_detected, attack_type = self._detect_attacks(frame, scores, details)

        return LivenessDetectionResult(
            is_live=is_live,
            score=float(ensemble_score),
            method="ensemble",
            details={
                "individual_scores": scores,
                "combined_method": self.config.ensemble_method,
                **details,
            },
            quality_metrics=details.get("deep_learning", {}).get("quality_metrics", {}),
            attack_detected=attack_detected,
            attack_type=attack_type,
        )

    # ─── Helper Methods ──────────────────────────────────────────────────────

    def _compute_lbp(self, gray: np.ndarray) -> np.ndarray:
        """Compute Local Binary Pattern of grayscale image."""
        return self._core.compute_lbp(gray)

    def _to_grayscale_uint8(self, frame: np.ndarray) -> np.ndarray:
        """Normalize incoming frames before grayscale conversion."""
        return self._core.to_grayscale_uint8(frame)

    def _compute_eye_aspect_ratio(self, eye_landmarks: np.ndarray) -> float:
        """Compute a simple eye aspect ratio from six 2D landmark points."""
        if eye_landmarks is None or len(eye_landmarks) < 6:
            return 0.0

        points = np.asarray(eye_landmarks, dtype=np.float32)
        horizontal = np.linalg.norm(points[2] - points[0])
        if horizontal <= 1e-6:
            return 0.0

        vertical_left = np.linalg.norm(points[1] - points[4])
        vertical_right = np.linalg.norm(points[2] - points[5])
        return float((vertical_left + vertical_right) / (2.0 * horizontal))

    def _detect_blinks(self, gray_frames: List[np.ndarray]) -> int:
        """
        Detect eye blinks by analyzing sudden brightness changes.
        """
        eye_counts = self._detect_eye_counts(gray_frames)
        return self._core.detect_blinks(gray_frames, eye_counts=eye_counts)

    def _analyze_frame_quality(self, frame: np.ndarray) -> Dict[str, float]:
        """Analyze frame quality metrics."""
        return self._core.analyze_frame_quality(frame)

    def _detect_attacks(
        self,
        frame: Optional[np.ndarray],
        scores: Dict[str, float],
        details: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """
        Detect specific spoofing attacks.
        
        Returns:
            (attack_detected, attack_type)
        """
        attack_detected = False
        attack_type = None

        if frame is None:
            return False, None

        # Print attack detection: flat colors, low texture entropy
        if self.config.detect_print_attacks:
            texture_details = details.get("texture", {})
            entropy = texture_details.get("entropy_normalized", 0.5)
            # Print/photo attacks have very low entropy
            if entropy < 0.3:
                attack_detected = True
                attack_type = "print_attack"
                return attack_detected, attack_type

        # Replay attack detection: no motion despite presence of face
        if self.config.detect_replay_attacks and "motion" in scores:
            motion_details = details.get("motion", {})
            avg_flow = motion_details.get("avg_optical_flow", 0)
            # Replay attacks show minimal motion
            if avg_flow < 1.0 and scores.get("texture", 0.5) > 0.6:
                # High texture score but no motion = suspicious
                attack_detected = True
                attack_type = "replay_attack"
                return attack_detected, attack_type

        # Mask attack detection: could integrate face recognition confidence
        # For now, check if frame quality is suspiciously good (could be mask)
        if self.config.detect_mask_attacks:
            quality = details.get("deep_learning", {}).get("quality_metrics", {})
            blur = quality.get("blur_score", 1.0)
            # Masks sometimes show unnaturally sharp edges
            if blur < 0.15 and scores.get("texture", 0.5) > 0.7:
                attack_detected = True
                attack_type = "mask_attack"

        return attack_detected, attack_type

    # ─── Challenge Verification ──────────────────────────────────────────────

    def verify_challenge(
        self,
        challenge_type: str,
        frames: List[np.ndarray],
        fps: int = 30,
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Verify whether the user performed the requested challenge action.

        Supported challenge types:
          - "blink"     – detect at least one blink in the video frames
          - "head_turn" – detect significant lateral head motion
          - "smile"     – detect brightness change in lower-face region

        Returns:
            (passed, confidence, details)
        """
        if len(frames) < 2:
            return False, 0.0, {"error": "Need at least 2 frames to verify challenge"}

        verifiers = {
            "blink": self._verify_blink_challenge,
            "head_turn": self._verify_head_turn_challenge,
            "smile": self._verify_smile_challenge,
        }

        verifier = verifiers.get(challenge_type)
        if verifier is None:
            return False, 0.0, {"error": f"Unknown challenge type: {challenge_type}"}

        try:
            return verifier(frames, fps)
        except Exception as e:
            logger.error("Challenge verification (%s) failed: %s", challenge_type, e)
            return False, 0.0, {"error": str(e)}

    # ── individual verifiers ──────────────────────────────────────────────

    def _verify_blink_challenge(
        self, frames: List[np.ndarray], fps: int
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Verify a blink challenge using MediaPipe facial landmarks.
        
        Uses eye aspect ratio (EAR) to detect blinks. A blink is a rapid drop
        and recovery in EAR values.
        """
        if not MEDIAPIPE_AVAILABLE or self.face_mesh is None:
            # Fallback: simple brightness-based detection
            gray_frames = [self._to_grayscale_uint8(f) for f in frames]
            blinks = self._detect_blinks(gray_frames)
            confidence = min(1.0, blinks / max(1, 1))
            passed = blinks >= 1
            eye_counts = self._detect_eye_counts(gray_frames)
            fallback_method = "haar_eye_state" if eye_counts and any(count > 0 for count in eye_counts) else "brightness_fallback"
            return passed, confidence, {
                "blinks_detected": blinks,
                "required": 1,
                "method": fallback_method,
                "eye_counts": eye_counts,
            }
        
        eye_aspect_ratios = []
        
        for frame in frames:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb_frame)
            
            if not results.multi_face_landmarks:
                continue
            
            landmarks = results.multi_face_landmarks[0].landmark
            
            # Left eye: landmarks 33, 160, 158, 133, 153, 144
            # Right eye: landmarks 362, 385, 387, 373, 380, 381
            left_eye = np.array([
                [landmarks[33].x, landmarks[33].y],
                [landmarks[160].x, landmarks[160].y],
                [landmarks[158].x, landmarks[158].y],
                [landmarks[133].x, landmarks[133].y],
                [landmarks[153].x, landmarks[153].y],
                [landmarks[144].x, landmarks[144].y],
            ])
            
            right_eye = np.array([
                [landmarks[362].x, landmarks[362].y],
                [landmarks[385].x, landmarks[385].y],
                [landmarks[387].x, landmarks[387].y],
                [landmarks[373].x, landmarks[373].y],
                [landmarks[380].x, landmarks[380].y],
                [landmarks[381].x, landmarks[381].y],
            ])
            
            # Calculate EAR for both eyes
            left_ear = self._compute_eye_aspect_ratio(left_eye)
            right_ear = self._compute_eye_aspect_ratio(right_eye)
            avg_ear = (left_ear + right_ear) / 2.0
            
            eye_aspect_ratios.append(avg_ear)
        
        if len(eye_aspect_ratios) < 5:
            return False, 0.0, {"error": "Not enough frames for blink detection"}
        
        # Detect blinks: EAR drops below threshold and recovers
        ear_array = np.array(eye_aspect_ratios)
        blink_threshold = 0.2  # Typical closed eye EAR
        
        # Find valleys (blinks) in EAR signal
        blinks = 0
        for i in range(1, len(ear_array) - 1):
            if (ear_array[i] < blink_threshold and 
                ear_array[i] < ear_array[i-1] and 
                ear_array[i] < ear_array[i+1]):
                blinks += 1
        
        confidence = min(1.0, blinks / 1.0)  # 1 blink = full confidence
        passed = blinks >= 1
        
        return passed, confidence, {
            "blinks_detected": int(blinks),
            "required": 1,
            "avg_ear": float(np.mean(ear_array)),
            "min_ear": float(np.min(ear_array)),
            "method": "mediapipe_landmarks",
        }

    def _verify_head_turn_challenge(
        self, frames: List[np.ndarray], fps: int
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Verify a head-turn challenge using optical flow and optionally MediaPipe pose.
        
        Detects significant lateral head motion through optical flow analysis
        and validates head rotation angles if MediaPipe is available.
        """
        normalized_frames = self._normalize_frame_sizes(frames)
        gray_frames = [self._to_grayscale_uint8(f) for f in normalized_frames]

        flow_mags: List[float] = []
        for i in range(len(gray_frames) - 1):
            flow = cv2.calcOpticalFlowFarneback(
                gray_frames[i], gray_frames[i + 1],
                None, 0.5, 3, 15, 3, 5, 1.2, 0,
            )
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            flow_mags.append(float(mag.mean()))

        avg_flow = float(np.mean(flow_mags)) if flow_mags else 0.0
        max_flow = float(np.max(flow_mags)) if flow_mags else 0.0

        # Real webcam captures produce modest dense-flow magnitudes even for
        # deliberate head turns. Require both a meaningful peak and a non-trivial
        # average motion so background flicker/noise does not pass the challenge.
        flow_threshold = 0.45
        avg_flow_threshold = 0.15
        passed = max_flow >= flow_threshold and avg_flow >= avg_flow_threshold
        confidence = min(1.0, max_flow / max(flow_threshold * 2, 1e-6))
        
        details: Dict[str, Any] = {
            "avg_optical_flow": avg_flow,
            "max_optical_flow": max_flow,
            "threshold": flow_threshold,
            "avg_flow_threshold": avg_flow_threshold,
            "method": "optical_flow",
        }

        face_track = self._track_face_motion(gray_frames)
        if len(face_track) >= 2:
            x_positions = [item[0] for item in face_track]
            widths = [item[2] for item in face_track]
            mean_width = max(1.0, float(np.mean(widths)))
            normalized_shift = float((max(x_positions) - min(x_positions)) / mean_width)
            normalized_width_change = float((max(widths) - min(widths)) / mean_width)
            face_motion_passed = normalized_shift >= 0.12 or normalized_width_change >= 0.08
            face_motion_confidence = min(
                1.0,
                max(
                    normalized_shift / 0.24,
                    normalized_width_change / 0.16,
                ),
            )

            details["face_center_shift_normalized"] = normalized_shift
            details["face_width_change_normalized"] = normalized_width_change
            details["face_track_samples"] = len(face_track)

            if face_motion_passed:
                passed = True
                confidence = max(confidence, face_motion_confidence)
                details["method"] = "optical_flow + face_track"
        
        # If MediaPipe is available, also check head pose rotations for additional validation
        if MEDIAPIPE_AVAILABLE and self.pose is not None:
            try:
                head_rotations = []
                for frame in frames:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = self.pose.process(rgb_frame)
                    if results.pose_landmarks:
                        # Use nose, left shoulder, right shoulder for head rotation estimation
                        nose = results.pose_landmarks[0]
                        l_shoulder = results.pose_landmarks[11]
                        r_shoulder = results.pose_landmarks[12]
                        
                        # Simple head tilt detection via shoulder angle asymmetry
                        shoulder_angle = np.arctan2(r_shoulder.y - l_shoulder.y, 
                                                   r_shoulder.x - l_shoulder.x)
                        head_rotations.append(float(shoulder_angle))
                
                if len(head_rotations) >= 2:
                    rotation_range = max(head_rotations) - min(head_rotations)
                    # A head turn should have > 0.3 radians (~17°) rotation
                    pose_threshold = 0.3
                    pose_valid = rotation_range > pose_threshold
                    
                    details["head_rotation_range"] = float(rotation_range)
                    details["pose_threshold"] = pose_threshold
                    details["pose_valid"] = pose_valid
                    details["method"] = "optical_flow + pose_estimation"
                    
                    # Combine optical flow and pose evidence
                    if pose_valid:
                        confidence = min(1.0, confidence + 0.2)
                    else:
                        confidence = max(0.0, confidence - 0.1)
            except Exception as e:
                logger.warning(f"Head pose estimation failed: {e}")
        
        return passed, confidence, details

    def _verify_smile_challenge(
        self, frames: List[np.ndarray], fps: int
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Verify a smile challenge using mouth region analysis and MediaPipe landmarks.
        
        A smile causes:
        1. Brightness variations in the mouth region
        2. Mouth corners moving upward (using landmarks if available)
        3. Changes in mouth openness
        """
        lower_brightness: List[float] = []
        mouth_openness: List[float] = []
        mouth_width: List[float] = []
        
        for frame in frames:
            gray = self._to_grayscale_uint8(frame)
            h = gray.shape[0]
            lower_half = gray[h // 2:, :]
            lower_brightness.append(float(lower_half.mean()))
            
            # If MediaPipe is available, get more precise mouth metrics
            if MEDIAPIPE_AVAILABLE and self.face_mesh is not None:
                try:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = self.face_mesh.process(rgb_frame)
                    
                    if results.multi_face_landmarks:
                        landmarks = results.multi_face_landmarks[0].landmark
                        
                        # Mouth landmarks: outer (top=13, bottom=14)
                        # and inner mouth (162=top, 82=bottom)
                        mouth_top = landmarks[13]
                        mouth_bottom = landmarks[14]
                        mouth_left = landmarks[78]
                        mouth_right = landmarks[308]
                        
                        # Mouth openness: vertical distance
                        openness = abs(mouth_bottom.y - mouth_top.y)
                        mouth_openness.append(float(openness))
                        
                        # Mouth width: horizontal distance
                        width = abs(mouth_right.x - mouth_left.x)
                        mouth_width.append(float(width))
                except Exception as e:
                    logger.debug(f"MediaPipe mouth detection failed: {e}")

        if len(lower_brightness) < 2:
            return False, 0.0, {"error": "Not enough frames"}

        brightness_range = max(lower_brightness) - min(lower_brightness)
        variance = float(np.var(lower_brightness))

        # Small exposure drift should not pass by itself; require a clearer lower-face shift.
        brightness_threshold = 6.0
        passed = brightness_range >= brightness_threshold
        confidence = min(1.0, brightness_range / (brightness_threshold * 3))
        
        details: Dict[str, Any] = {
            "brightness_range": brightness_range,
            "brightness_variance": variance,
            "brightness_threshold": brightness_threshold,
            "method": "brightness_analysis",
        }

        if not MEDIAPIPE_AVAILABLE or self.face_mesh is None:
            smile_scores = self._detect_smile_scores([self._to_grayscale_uint8(frame) for frame in frames])
            smile_frames = sum(1 for score in smile_scores if score > 0.015)
            smile_ratio = float(smile_frames / max(1, len(smile_scores))) if smile_scores else 0.0
            if smile_scores:
                details["smile_scores"] = [round(float(score), 4) for score in smile_scores]
                details["smile_frame_ratio"] = smile_ratio
                if smile_ratio >= 0.2:
                    passed = True
                    confidence = max(confidence, min(1.0, smile_ratio / 0.4))
                    details["method"] = "brightness_analysis + haar_smile"
        
        # If we have mouth landmarks, add that information
        if mouth_openness:
            openness_change = max(mouth_openness) - min(mouth_openness)
            width_range = max(mouth_width) - min(mouth_width)
            details["mouth_openness_change"] = float(openness_change)
            details["mouth_width_range"] = float(width_range)
            details["method"] = "brightness_analysis + mouth_landmarks"
            
            # Smile causes both brightness change and mouth corner movement
            if openness_change > 0.02:  # Significant mouth openness change
                confidence = min(1.0, confidence + 0.15)
            if width_range > 0.05:  # Smile widens mouth
                confidence = min(1.0, confidence + 0.15)
        
        return passed, confidence, details


# ─── Challenge Session Helpers ────────────────────────────────────────────────


def create_liveness_challenge(
    db: Session,
    organization_id: str,
    visitor_log_id: str,
    challenge_type: str = "blink",
    timeout_seconds: int = 30,
) -> LivenessChallenge:
    """Create a new liveness challenge session in the database."""
    instructions = {
        "blink": "Please blink naturally to complete liveness verification",
        "head_turn": "Please slowly turn your head left then right",
        "smile": "Please smile to complete liveness verification",
    }
    challenge = LivenessChallenge(
        organization_id=organization_id,
        visitor_log_id=visitor_log_id,
        challenge_type=challenge_type,
        instruction=instructions.get(challenge_type, f"Please {challenge_type}"),
        timeout_seconds=timeout_seconds,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    logger.info("Created liveness challenge %s (type=%s)", challenge.id, challenge_type)
    return challenge


def complete_liveness_challenge(
    db: Session,
    challenge: LivenessChallenge,
    verified: bool,
    confidence: float,
    details: Dict,
) -> LivenessChallenge:
    """Record the verification outcome of a liveness challenge."""
    challenge.verified = verified
    challenge.confidence = confidence
    challenge.details = details
    challenge.status = "verified" if verified else "failed"
    challenge.attempts = (challenge.attempts or 0) + 1
    challenge.verified_at = datetime.now()
    db.commit()
    db.refresh(challenge)
    return challenge


def create_liveness_score(
    db: Session,
    organization_id: str,
    visitor_log_id: str,
    request: LivenessScoreCreateRequest,
) -> LivenessScore:
    """Create a new liveness score record in database."""
    try:
        liveness_score = LivenessScore(
            organization_id=organization_id,
            visitor_log_id=visitor_log_id,
            **request.model_dump(exclude_unset=True, exclude={"visitor_log_id"}),
        )
        db.add(liveness_score)
        db.commit()
        db.refresh(liveness_score)
        logger.info(f"Created liveness score {liveness_score.id}")
        return liveness_score
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create liveness score: {e}")
        raise


def get_liveness_scores(
    db: Session,
    organization_id: str,
    visitor_log_id: Optional[str] = None,
    is_live: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[LivenessScore]:
    """Retrieve liveness scores with optional filters."""
    query = db.query(LivenessScore).filter(
        LivenessScore.organization_id == organization_id
    )

    if visitor_log_id:
        query = query.filter(LivenessScore.visitor_log_id == visitor_log_id)

    if is_live is not None:
        query = query.filter(LivenessScore.is_live == is_live)

    return query.order_by(LivenessScore.created_at.desc()).limit(limit).offset(offset).all()


def get_liveness_statistics(
    db: Session,
    organization_id: str,
) -> LivenessStatistics:
    """Calculate liveness statistics for organization."""
    scores = db.query(LivenessScore).filter(
        LivenessScore.organization_id == organization_id
    ).all()

    total = len(scores)
    live_count = sum(1 for s in scores if s.is_live)
    spoof_count = total - live_count

    if total == 0:
        return LivenessStatistics(
            total_detections=0,
            live_count=0,
            spoof_count=0,
            live_percentage=0.0,
            average_liveness_score=0.0,
            attack_detection_rate=0.0,
            average_processing_time_ms=0.0,
        )

    live_percentage = (live_count / total) * 100.0
    avg_score = np.mean([s.overall_score for s in scores])
    attack_count = sum(1 for s in scores if s.attack_indicators)
    attack_rate = (attack_count / total) * 100.0
    avg_time = np.mean([s.processing_time_ms or 0 for s in scores])

    # Most common rejection reason
    rejection_reasons = [s.rejection_reason for s in scores if s.rejection_reason]
    most_common_reason = None
    if rejection_reasons:
        most_common_reason = max(set(rejection_reasons), key=rejection_reasons.count)

    # Method distribution
    method_distribution = {}
    for s in scores:
        method = s.method_used
        method_distribution[method] = method_distribution.get(method, 0) + 1

    return LivenessStatistics(
        total_detections=total,
        live_count=live_count,
        spoof_count=spoof_count,
        live_percentage=float(live_percentage),
        average_liveness_score=float(avg_score),
        most_common_rejection_reason=most_common_reason,
        attack_detection_rate=float(attack_rate),
        average_processing_time_ms=float(avg_time),
        method_distribution=method_distribution,
    )
