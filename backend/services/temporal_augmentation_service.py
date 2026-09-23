"""
Temporal Face Augmentation Service (US-FUT-021)

Generates diverse facial expressions over time for training data augmentation.
Includes expression detection, interpolation, and video synthesis.
"""

import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
import logging
from datetime import datetime, timezone
import uuid
from pathlib import Path
import os

try:
    import torch
except Exception:  # pragma: no cover - torch may be unavailable in lightweight test envs
    torch = None

from sqlalchemy.orm import Session
from db.base import SessionLocal
from models.models import (
    TemporalAugmentationConfig, AugmentationJob, GeneratedSequence,
    ExpressionMetrics
)

logger = logging.getLogger(__name__)


class ExpressionDetector:
    """Detects facial expressions (Placeholder logic for training models)."""
    
    def __init__(self):
        # In a real app, this would load a pre-trained expression model
        self.expressions = ["neutral", "happy", "sad", "angry", "surprised"]
    
    def detect_expression(self, frame: np.ndarray) -> Tuple[str, float]:
        """Detect expression in frame using simple intensity heuristics."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        upper = gray[: max(1, h // 3), :]
        middle = gray[max(1, h // 3): max(2, (2 * h) // 3), :]
        lower = gray[max(2, (2 * h) // 3):, :]

        brightness_delta = float(lower.mean() - upper.mean()) / 255.0
        contrast = float(gray.std() / 64.0)
        center_bias = float(middle.mean() / 255.0)

        if brightness_delta > 0.08:
            expr = "happy"
        elif brightness_delta < -0.08:
            expr = "sad"
        elif contrast > 0.95:
            expr = "surprised"
        elif center_bias < 0.35:
            expr = "angry"
        else:
            expr = "neutral"

        conf = max(0.55, min(0.98, 0.65 + (contrast * 0.15) + abs(brightness_delta) * 0.4))
        return expr, conf


class TemporalTransitionModel:
    """Optional temporal synthesis model with deterministic fallback behavior."""

    def __init__(self):
        self.model_path = (os.getenv("TEMPORAL_SYNTH_MODEL_PATH") or "").strip()
        self.model = None
        self.available = False

        if torch is None or not self.model_path:
            return
        if not os.path.exists(self.model_path):
            logger.warning("Temporal synthesis model path not found: %s", self.model_path)
            return

        try:
            loaded = torch.jit.load(self.model_path, map_location="cpu")
            loaded.eval()
            self.model = loaded
            self.available = True
            logger.info("Loaded temporal synthesis model: %s", self.model_path)
        except Exception as exc:
            logger.warning("Failed to load temporal synthesis model (%s): %s", self.model_path, exc)
            self.model = None
            self.available = False

    @staticmethod
    def _to_tensor(frame: np.ndarray) -> "torch.Tensor":
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        chw = np.transpose(rgb, (2, 0, 1))
        return torch.from_numpy(chw).unsqueeze(0)

    @staticmethod
    def _to_frame(tensor: "torch.Tensor") -> np.ndarray:
        chw = tensor.detach().cpu().float().squeeze(0)
        if chw.shape[0] > 3:
            chw = chw[:3]
        if chw.shape[0] == 1:
            chw = chw.repeat(3, 1, 1)
        chw = torch.clamp(chw, 0.0, 1.0)
        rgb = np.transpose(chw.numpy(), (1, 2, 0))
        bgr = cv2.cvtColor((rgb * 255.0).astype(np.uint8), cv2.COLOR_RGB2BGR)
        return bgr

    def refine_frame(
        self,
        source_frame: np.ndarray,
        target_frame: np.ndarray,
        alpha: float,
    ) -> Optional[np.ndarray]:
        """Refine blended transition frame with an optional Torch model."""
        if not self.available or self.model is None or torch is None:
            return None

        try:
            source = self._to_tensor(source_frame)
            target = self._to_tensor(target_frame)
            alpha_tensor = torch.tensor([[float(alpha)]], dtype=torch.float32)

            with torch.no_grad():
                candidate = ((1.0 - alpha) * source) + (alpha * target)
                try:
                    output = self.model(candidate, source, target, alpha_tensor)
                except TypeError:
                    output = self.model(candidate)
                if isinstance(output, (tuple, list)):
                    output = output[0]
                if not isinstance(output, torch.Tensor):
                    return None

            return self._to_frame(output)
        except Exception as exc:
            logger.debug("Temporal synthesis refinement skipped: %s", exc)
            return None


class ExpressionInterpolator:
    """Interpolates between facial expressions using morphing techniques."""

    def __init__(self):
        self.transition_model = TemporalTransitionModel()

    @staticmethod
    def _smoothstep(alpha: float) -> float:
        return (3.0 * (alpha ** 2)) - (2.0 * (alpha ** 3))

    def _target_expression_frame(
        self,
        frame_start: np.ndarray,
        target_expression: str,
    ) -> np.ndarray:
        """Generate a target-expression frame used as the temporal interpolation endpoint."""
        frame = frame_start.copy()
        h, w = frame.shape[:2]

        mouth_slice = (
            slice(max(0, int(h * 0.58)), min(h, int(h * 0.84))),
            slice(max(0, int(w * 0.22)), min(w, int(w * 0.78))),
        )
        brow_slice = (
            slice(max(0, int(h * 0.18)), min(h, int(h * 0.42))),
            slice(max(0, int(w * 0.18)), min(w, int(w * 0.82))),
        )
        eye_slice = (
            slice(max(0, int(h * 0.26)), min(h, int(h * 0.48))),
            slice(max(0, int(w * 0.18)), min(w, int(w * 0.82))),
        )

        if target_expression == "happy":
            mouth = frame[mouth_slice].copy()
            mouth = cv2.resize(
                mouth,
                None,
                fx=1.06,
                fy=0.9,
                interpolation=cv2.INTER_LINEAR,
            )
            mouth = cv2.convertScaleAbs(mouth, alpha=1.08, beta=12)
            frame[mouth_slice] = cv2.resize(
                mouth,
                (mouth_slice[1].stop - mouth_slice[1].start, mouth_slice[0].stop - mouth_slice[0].start),
            )
        elif target_expression == "sad":
            frame[mouth_slice] = cv2.convertScaleAbs(frame[mouth_slice], alpha=0.94, beta=-10)
            frame[brow_slice] = cv2.convertScaleAbs(frame[brow_slice], alpha=0.96, beta=-8)
        elif target_expression == "angry":
            frame[brow_slice] = cv2.convertScaleAbs(frame[brow_slice], alpha=1.14, beta=-9)
            frame[eye_slice] = cv2.convertScaleAbs(frame[eye_slice], alpha=0.93, beta=-5)
        elif target_expression == "surprised":
            eyes = frame[eye_slice].copy()
            eyes = cv2.resize(eyes, None, fx=1.03, fy=1.13, interpolation=cv2.INTER_LINEAR)
            frame[eye_slice] = cv2.resize(
                eyes,
                (eye_slice[1].stop - eye_slice[1].start, eye_slice[0].stop - eye_slice[0].start),
            )
            frame[mouth_slice] = cv2.convertScaleAbs(frame[mouth_slice], alpha=1.08, beta=14)

        frame = cv2.GaussianBlur(frame, (3, 3), sigmaX=0.8)
        return frame

    def _optical_flow_transition(
        self,
        frame_start: np.ndarray,
        frame_target: np.ndarray,
        num_frames: int,
    ) -> List[np.ndarray]:
        if num_frames <= 0:
            return []

        start_gray = cv2.cvtColor(frame_start, cv2.COLOR_BGR2GRAY)
        target_gray = cv2.cvtColor(frame_target, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(
            start_gray,
            target_gray,
            None,
            0.5,
            3,
            15,
            3,
            5,
            1.2,
            0,
        )

        h, w = start_gray.shape[:2]
        grid_x, grid_y = np.meshgrid(
            np.arange(w, dtype=np.float32),
            np.arange(h, dtype=np.float32),
        )

        sequence: List[np.ndarray] = []
        for alpha_raw in np.linspace(0.0, 1.0, num_frames):
            alpha = float(self._smoothstep(float(alpha_raw)))
            map_x = grid_x + (flow[..., 0] * alpha)
            map_y = grid_y + (flow[..., 1] * alpha)
            warped = cv2.remap(
                frame_start,
                map_x,
                map_y,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )

            blended = cv2.addWeighted(warped, 1.0 - alpha, frame_target, alpha, 0.0)
            refined = self.transition_model.refine_frame(
                source_frame=warped,
                target_frame=frame_target,
                alpha=alpha,
            )
            if refined is not None:
                blended = cv2.addWeighted(blended, 0.45, refined, 0.55, 0.0)

            sequence.append(blended)

        return sequence
    
    def interpolate_expression(
        self,
        frame_start: np.ndarray,
        target_expression: str,
        num_frames: int,
        method: str = "bezier"
    ) -> List[np.ndarray]:
        """Interpolate between expressions using temporal transition synthesis."""
        if num_frames <= 0:
            return []

        target_frame = self._target_expression_frame(frame_start, target_expression)

        if method in {"direct", "blend"}:
            return [
                cv2.addWeighted(
                    frame_start,
                    1.0 - float(alpha),
                    target_frame,
                    float(alpha),
                    0.0,
                )
                for alpha in np.linspace(0.0, 1.0, num_frames)
            ]

        # Default path uses optical-flow warping to build smoother temporal
        # transitions, with optional Torch refinement when available.
        return self._optical_flow_transition(
            frame_start=frame_start,
            frame_target=target_frame,
            num_frames=num_frames,
        )


class VideoProcessor:
    """Utilities for reading and writing augmented video sequences."""
    
    @staticmethod
    def read_video_frames(video_path: str, max_frames: int = 300) -> List[np.ndarray]:
        """Read frames from video file."""
        frames = []
        if not os.path.exists(video_path):
            return []
            
        cap = cv2.VideoCapture(video_path)
        count = 0
        while cap.isOpened() and count < max_frames:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
            count += 1
        cap.release()
        return frames

    @staticmethod
    def validate_video_input(video_path: str) -> Tuple[bool, str | None]:
        if not video_path:
            return False, "Input video path is required"
        if not os.path.exists(video_path):
            return False, "Input video does not exist"
        if os.path.isdir(video_path):
            return False, "Input video path points to a directory"
        if Path(video_path).suffix.lower() not in {".mp4", ".avi", ".mov", ".mkv", ".webm"}:
            return False, "Unsupported video format"
        return True, None

    @staticmethod
    def estimate_optical_flow_smoothness(frames: List[np.ndarray]) -> float:
        if len(frames) < 2:
            return 1.0

        magnitudes: List[float] = []
        prev_gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
        for frame in frames[1:]:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray,
                gray,
                None,
                0.5,
                3,
                15,
                3,
                5,
                1.2,
                0,
            )
            magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
            magnitudes.append(float(np.mean(magnitude)))
            prev_gray = gray

        if not magnitudes:
            return 1.0
        mean_magnitude = float(np.mean(magnitudes))
        return max(0.0, min(1.0, 1.0 - (mean_magnitude / 6.0)))
    
    @staticmethod
    def write_video(frames: List[np.ndarray], output_path: str, fps: int = 30) -> bool:
        """Write sequence of frames to an MP4 video."""
        if not frames:
            return False
            
        height, width = frames[0].shape[:2]
        # Use mp4v for compatibility across OSs
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        for frame in frames:
            out.write(frame)
        out.release()
        return True


class TemporalAugmentationService:
    """Orchestrates temporal face sequence generation."""
    
    def __init__(self):
        self.expression_detector = ExpressionDetector()
        self.interpolator = ExpressionInterpolator()
        self.video_processor = VideoProcessor()
    
    async def run_augmentation_job(self, job_id: str):
        """Execute a temporal augmentation job asynchronously using its own DB session."""
        db = SessionLocal()
        try:
            await self._run_augmentation_job(db, job_id)
        finally:
            db.close()

    async def _run_augmentation_job(self, db: Session, job_id: str):
        job = db.query(AugmentationJob).filter_by(id=job_id).first()
        if not job:
            return

        config = db.query(TemporalAugmentationConfig).filter_by(id=job.config_id).first()
        if not config:
            job.status = "failed"
            job.error_message = "Config not found"
            db.commit()
            return

        expression_distribution: Dict[str, int] = {}
        transition_distribution: Dict[str, int] = {}
        confidence_scores: List[float] = []

        try:
            job.status = "running"
            job.error_message = None
            job.started_at = datetime.now(timezone.utc)
            db.commit()

            is_valid_input, validation_error = self.video_processor.validate_video_input(job.input_video_path or "")
            if not is_valid_input:
                job.status = "failed"
                job.error_message = validation_error
                db.commit()
                return

            frames = self.video_processor.read_video_frames(job.input_video_path)
            if not frames:
                job.status = "failed"
                job.error_message = "Input video not found or invalid"
                db.commit()
                return

            job.total_frames = len(frames)
            output_dir = Path(f"data/temporal/{job.id}")
            output_dir.mkdir(parents=True, exist_ok=True)

            generated_count = 0
            for i, frame in enumerate(frames):
                db.refresh(job)
                if (job.status or "").lower() == "cancelled":
                    job.completed_at = datetime.now(timezone.utc)
                    job.duration_seconds = (job.completed_at - job.started_at).total_seconds() if job.started_at else None
                    db.commit()
                    return

                source_expr, source_conf = self.expression_detector.detect_expression(frame)
                confidence_scores.append(source_conf)
                expression_distribution[source_expr] = expression_distribution.get(source_expr, 0) + 1

                for target_expr, weight in (config.target_expressions or {}).items():
                    if target_expr == source_expr or weight <= 0:
                        continue

                    interpolated = self.interpolator.interpolate_expression(
                        frame, target_expr, config.frames_per_transition, config.interpolation_method
                    )

                    if interpolated:
                        filename = f"seq_{i}_{target_expr}.mp4"
                        output_path = output_dir / filename

                        if self.video_processor.write_video(interpolated, str(output_path), config.fps):
                            file_size = output_path.stat().st_size if output_path.exists() else None
                            duration_seconds = len(interpolated) / max(int(config.fps or 1), 1)
                            optical_flow_smoothness = self.video_processor.estimate_optical_flow_smoothness(interpolated)
                            sequence = GeneratedSequence(
                                id=str(uuid.uuid4()),
                                organization_id=job.organization_id,
                                job_id=job.id,
                                config_id=config.id,
                                video_path=str(output_path),
                                file_size=file_size,
                                duration_seconds=duration_seconds,
                                source_expression=source_expr,
                                target_expression=target_expr,
                                transition_type=config.interpolation_method,
                                frame_count=len(interpolated),
                                fps=config.fps,
                                expression_confidence_target=source_conf,
                                optical_flow_smoothness=optical_flow_smoothness,
                            )
                            db.add(sequence)
                            generated_count += 1
                            transition_key = f"{source_expr}->{target_expr}"
                            transition_distribution[transition_key] = transition_distribution.get(transition_key, 0) + 1

                job.processed_frames = i + 1
                if i % 5 == 0:
                    db.commit()

            job.generated_sequences = generated_count
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.duration_seconds = (job.completed_at - job.started_at).total_seconds()
            job.avg_expression_confidence = float(np.mean(confidence_scores)) if confidence_scores else None
            sequence_rows = db.query(GeneratedSequence).filter_by(job_id=job.id).all()
            optical_flow_values = [
                float(row.optical_flow_smoothness) for row in sequence_rows
                if row.optical_flow_smoothness is not None
            ]
            job.avg_optical_flow = float(np.mean(optical_flow_values)) if optical_flow_values else None

            db.add(
                ExpressionMetrics(
                    id=str(uuid.uuid4()),
                    organization_id=job.organization_id,
                    job_id=job.id,
                    expression_distribution=expression_distribution,
                    transition_distribution=transition_distribution,
                    avg_confidence=job.avg_expression_confidence,
                    acceptance_rate=(
                        float(job.generated_sequences or 0) / max(int(job.total_frames or 0), 1)
                    ),
                )
            )
            db.commit()

        except Exception as e:
            logger.error(f"Temporal augmentation failed: {e}")
            db.rollback()
            job = db.query(AugmentationJob).filter_by(id=job_id).first()
            if job:
                job.status = "failed"
                job.error_message = str(e)
                db.commit()


