from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


class LivenessCore:
    """Core liveness algorithms shared across backend and AI services."""

    def __init__(self, model_path: Optional[str] = None) -> None:
        self.model_path = Path(model_path or "models/liveness_net.onnx")
        self._net: Optional[Any] = None  # cached cv2.dnn network

    @staticmethod
    def normalize_score(score: Any, fallback: float = 0.5) -> float:
        try:
            normalized = float(score)
        except (TypeError, ValueError):
            return fallback
        if not np.isfinite(normalized):
            return fallback
        return max(0.0, min(1.0, normalized))

    @staticmethod
    def normalize_frame_sizes(frames: List[np.ndarray]) -> List[np.ndarray]:
        valid_frames = [frame for frame in frames if frame is not None and frame.size != 0]
        if not valid_frames:
            return []

        heights = [frame.shape[0] for frame in valid_frames]
        widths = [frame.shape[1] for frame in valid_frames]
        target_height = max(1, min(heights))
        target_width = max(1, min(widths))

        normalized: List[np.ndarray] = []
        for frame in valid_frames:
            if frame.shape[0] == target_height and frame.shape[1] == target_width:
                normalized.append(frame)
            else:
                normalized.append(
                    cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_LINEAR)
                )
        return normalized

    @staticmethod
    def to_grayscale_uint8(frame: np.ndarray) -> np.ndarray:
        array = np.asarray(frame)
        if array.dtype != np.uint8:
            array = np.clip(array, 0, 255).astype(np.uint8)
        return cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def compute_lbp(gray: np.ndarray) -> np.ndarray:
        height, width = gray.shape
        lbp = np.zeros((height, width), dtype=np.uint8)

        for i in range(1, height - 1):
            for j in range(1, width - 1):
                center = gray[i, j]
                neighbors = [
                    gray[i - 1, j - 1], gray[i - 1, j], gray[i - 1, j + 1],
                    gray[i, j + 1], gray[i + 1, j + 1], gray[i + 1, j],
                    gray[i + 1, j - 1], gray[i, j - 1],
                ]
                lbp_code = 0
                for k, neighbor in enumerate(neighbors):
                    lbp_code |= (1 << k) if neighbor >= center else 0
                lbp[i, j] = lbp_code

        return lbp

    @staticmethod
    def analyze_frame_quality(frame: np.ndarray) -> Dict[str, float]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        illumination_score = max(0.3, min(1.0, gray.mean() / 255.0))
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        blur_score = max(0.0, min(1.0, 1.0 - (laplacian_var / 500.0)))
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        noise_estimate = cv2.absdiff(gray, blurred).mean() / 255.0
        noise_level = min(1.0, noise_estimate * 2)
        return {
            "illumination_score": float(illumination_score),
            "blur_score": float(blur_score),
            "noise_level": float(noise_level),
            "laplacian_variance": float(laplacian_var),
            "average_brightness": float(gray.mean()),
        }

    @staticmethod
    def detect_blinks(
        gray_frames: List[np.ndarray],
        eye_counts: Optional[List[int]] = None,
    ) -> int:
        if len(gray_frames) < 2:
            return 0

        if eye_counts and any(count > 0 for count in eye_counts):
            blink_count = 0
            had_open_state = False
            closed_run = 0
            min_closed_frames = 1

            for eye_count in eye_counts:
                eyes_open = eye_count >= 1
                if eyes_open:
                    if had_open_state and closed_run >= min_closed_frames:
                        blink_count += 1
                    had_open_state = True
                    closed_run = 0
                elif had_open_state:
                    closed_run += 1

            if blink_count > 0:
                return blink_count

        brightness_changes = []
        for i in range(1, len(gray_frames)):
            diff = cv2.absdiff(gray_frames[i - 1], gray_frames[i])
            brightness_changes.append(diff.mean())

        blink_count = 0
        for i in range(1, len(brightness_changes) - 1):
            if (
                brightness_changes[i] > brightness_changes[i - 1]
                and brightness_changes[i] > brightness_changes[i + 1]
                and brightness_changes[i] > 10
            ):
                blink_count += 1

        return blink_count

    def texture_score(self, frame: np.ndarray) -> Tuple[float, Dict[str, Any]]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        lbp_image = self.compute_lbp(gray)

        hist, _ = np.histogram(lbp_image.ravel(), bins=256, range=(0, 256))
        hist = hist / (hist.sum() + 1e-7)

        entropy = -np.sum(hist * np.log2(hist + 1e-7))
        entropy_normalized = entropy / 8.0

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        s_channel = hsv[:, :, 1].astype(float)
        saturation_variance = np.var(s_channel) / 255.0

        texture_score = 0.7 * entropy_normalized + 0.3 * min(saturation_variance * 2, 1.0)

        return float(texture_score), {
            "entropy": float(entropy),
            "entropy_normalized": float(entropy_normalized),
            "saturation_variance": float(saturation_variance),
            "lbp_histogram_peaks": int(np.sum(hist > hist.max() * 0.1)),
        }

    def motion_score(
        self,
        frames: List[np.ndarray],
        fps: int = 30,
        eye_counts: Optional[List[int]] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        if len(frames) < 2:
            return 0.0, {"error": "Need at least 2 frames for motion detection"}

        normalized_frames = self.normalize_frame_sizes(frames)
        gray_frames = [self.to_grayscale_uint8(f) for f in normalized_frames]

        flow_magnitudes = []
        for i in range(len(gray_frames) - 1):
            flow = cv2.calcOpticalFlowFarneback(
                gray_frames[i], gray_frames[i + 1],
                None, 0.5, 3, 15, 3, 5, 1.2, 0,
            )
            magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            flow_magnitudes.append(magnitude)

        avg_motion = np.mean([m.mean() for m in flow_magnitudes]) if flow_magnitudes else 0.0
        motion_variance = np.var([m.mean() for m in flow_magnitudes]) if flow_magnitudes else 0.0
        blink_count = self.detect_blinks(gray_frames, eye_counts=eye_counts)

        motion_score = min(avg_motion / 10.0, 1.0) * 0.6
        motion_score += min(motion_variance / 5.0, 0.4)
        blink_bonus = min(blink_count * 0.1, 0.2)
        motion_score = min(motion_score + blink_bonus, 1.0)

        return float(motion_score), {
            "avg_optical_flow": float(avg_motion),
            "flow_variance": float(motion_variance),
            "blink_count": int(blink_count),
            "video_duration_frames": len(frames),
            "video_duration_seconds": len(frames) / fps,
        }

    def spectral_score(self, frame: np.ndarray) -> Tuple[float, Dict[str, Any]]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (128, 128)).astype(np.float32)

        cnn_score: Optional[float] = None
        cnn_used = False

        if self.model_path.exists():
            try:
                if self._net is None:
                    self._net = cv2.dnn.readNetFromONNX(str(self.model_path))
                net = self._net
                blob = cv2.dnn.blobFromImage(
                    frame, scalefactor=1.0 / 255.0,
                    size=(128, 128), mean=(0, 0, 0),
                    swapRB=True, crop=True,
                )
                net.setInput(blob)
                output = net.forward()
                if output.shape[-1] == 2:
                    cnn_score = float(output[0][1])
                else:
                    cnn_score = float(output[0][0])
                cnn_score = max(0.0, min(1.0, cnn_score))
                cnn_used = True
            except Exception:
                cnn_score = None
                cnn_used = False

        dct = cv2.dct(resized)
        total_energy = np.sum(dct ** 2) + 1e-7
        low_freq = np.sum(dct[:32, :32] ** 2)
        high_freq = total_energy - low_freq
        hf_ratio = high_freq / total_energy
        dct_score = min(1.0, max(0.0, (hf_ratio - 0.05) / 0.30))

        ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
        cr_channel = ycrcb[:, :, 1].astype(np.float32)
        cb_channel = ycrcb[:, :, 2].astype(np.float32)

        cr_std = np.std(cr_channel)
        cb_std = np.std(cb_channel)
        cr_mean = np.mean(cr_channel)
        cb_mean = np.mean(cb_channel)

        cr_in_range = 1.0 if 133 <= cr_mean <= 173 else max(0.0, 1.0 - abs(cr_mean - 153) / 50)
        cb_in_range = 1.0 if 77 <= cb_mean <= 127 else max(0.0, 1.0 - abs(cb_mean - 102) / 50)
        chroma_variance = min(1.0, (cr_std + cb_std) / 40.0)
        color_score = 0.4 * cr_in_range + 0.3 * cb_in_range + 0.3 * chroma_variance

        f_transform = np.fft.fft2(resized)
        f_shift = np.fft.fftshift(f_transform)
        magnitude = np.abs(f_shift)

        cy, cx = magnitude.shape[0] // 2, magnitude.shape[1] // 2
        magnitude[cy - 2:cy + 3, cx - 2:cx + 3] = 0

        peak_threshold = np.mean(magnitude) + 3 * np.std(magnitude)
        num_peaks = np.sum(magnitude > peak_threshold)
        peak_ratio = num_peaks / magnitude.size
        moire_score = max(0.0, min(1.0, 1.0 - peak_ratio * 50))

        quality_metrics = self.analyze_frame_quality(frame)

        if cnn_used and cnn_score is not None:
            dl_score = cnn_score * 0.60 + dct_score * 0.15 + color_score * 0.15 + moire_score * 0.10
        else:
            dl_score = (
                dct_score * 0.35
                + color_score * 0.30
                + moire_score * 0.25
                + quality_metrics.get("illumination_score", 0.5) * 0.05
                + (1.0 - quality_metrics.get("blur_score", 0.5)) * 0.05
            )

        return float(dl_score), {
            "quality_metrics": quality_metrics,
            "model_version": "liveness_v2_cnn" if cnn_used else "liveness_v2_spectral",
            "model_type": "cnn+spectral" if cnn_used else "spectral+chrominance+moire",
            "cnn_available": cnn_used,
            "cnn_score": cnn_score,
            "dct_score": float(dct_score),
            "dct_hf_ratio": float(hf_ratio),
            "color_score": float(color_score),
            "cr_mean": float(cr_mean),
            "cb_mean": float(cb_mean),
            "chroma_variance": float(chroma_variance),
            "moire_score": float(moire_score),
            "moire_peak_ratio": float(peak_ratio),
        }
