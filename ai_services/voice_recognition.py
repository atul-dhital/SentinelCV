"""
Voice Recognition Service (ENH-015)

Speaker identification and verification using audio features.
Extracts MFCC and spectral features from audio, computes 128-dim
voice embeddings, and performs speaker matching and liveness detection.
"""

import logging
import math
import numpy as np
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import audio processing libraries
try:
    import scipy.io.wavfile as wavfile
    from scipy.fft import fft, rfft
    from scipy.signal import stft

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


class VoiceRecognitionService:
    """Speaker identification using voice features."""

    SAMPLE_RATE = 16000
    N_MFCC = 20
    N_FFT = 512
    HOP_LENGTH = 160
    EMBEDDING_DIM = 128

    def __init__(self):
        self._mel_filterbank = self._create_mel_filterbank(
            n_filters=40, n_fft=self.N_FFT, sample_rate=self.SAMPLE_RATE
        )

    def _create_mel_filterbank(
        self, n_filters: int, n_fft: int, sample_rate: int
    ) -> np.ndarray:
        """Create Mel-scale filterbank for MFCC computation."""
        low_mel = self._hz_to_mel(0)
        high_mel = self._hz_to_mel(sample_rate / 2)
        mel_points = np.linspace(low_mel, high_mel, n_filters + 2)
        hz_points = self._mel_to_hz(mel_points)
        bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

        filterbank = np.zeros((n_filters, n_fft // 2 + 1))
        for i in range(n_filters):
            left = bin_points[i]
            center = bin_points[i + 1]
            right = bin_points[i + 2]
            for j in range(left, center):
                if center > left:
                    filterbank[i, j] = (j - left) / (center - left)
            for j in range(center, right):
                if right > center:
                    filterbank[i, j] = (right - j) / (right - center)

        return filterbank

    @staticmethod
    def _hz_to_mel(hz: float) -> float:
        return 2595 * math.log10(1 + hz / 700)

    @staticmethod
    def _mel_to_hz(mel: np.ndarray) -> np.ndarray:
        return 700 * (10 ** (mel / 2595) - 1)

    def _compute_mfcc(self, audio: np.ndarray) -> np.ndarray:
        """Compute Mel-Frequency Cepstral Coefficients."""
        # Pre-emphasis
        emphasized = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])

        # Framing
        frame_length = self.N_FFT
        num_frames = max(1, (len(emphasized) - frame_length) // self.HOP_LENGTH + 1)
        frames = np.zeros((num_frames, frame_length))
        for i in range(num_frames):
            start = i * self.HOP_LENGTH
            end = start + frame_length
            frame = emphasized[start:end]
            frames[i, : len(frame)] = frame

        # Windowing (Hamming)
        window = np.hamming(frame_length)
        frames *= window

        # FFT
        magnitude = np.abs(np.fft.rfft(frames, n=self.N_FFT))
        power_spectrum = magnitude ** 2 / self.N_FFT

        # Mel filterbank
        mel_spec = np.dot(power_spectrum, self._mel_filterbank.T)
        mel_spec = np.maximum(mel_spec, 1e-10)
        log_mel = np.log(mel_spec)

        # DCT (to get cepstral coefficients)
        n_filters = log_mel.shape[1]
        dct_matrix = np.zeros((self.N_MFCC, n_filters))
        for i in range(self.N_MFCC):
            for j in range(n_filters):
                dct_matrix[i, j] = math.cos(math.pi * i * (j + 0.5) / n_filters)

        mfcc = np.dot(log_mel, dct_matrix.T)
        return mfcc

    def extract_voice_features(self, audio_path: str) -> Dict:
        """
        Extract voice features from an audio file.

        Returns MFCCs, spectral features, and prosodic features.
        """
        try:
            audio = self._load_audio(audio_path)
        except Exception as e:
            logger.error(f"Failed to load audio: {e}")
            return {"valid": False, "error": str(e)}

        if len(audio) < self.SAMPLE_RATE * 0.5:  # Less than 0.5 seconds
            return {"valid": False, "error": "Audio too short (need at least 0.5 seconds)"}

        # MFCC features
        mfcc = self._compute_mfcc(audio)

        # Spectral features
        spectral = self._spectral_features(audio)

        # Prosodic features (pitch, energy, speaking rate)
        prosodic = self._prosodic_features(audio)

        return {
            "valid": True,
            "duration_seconds": len(audio) / self.SAMPLE_RATE,
            "mfcc_mean": mfcc.mean(axis=0).tolist(),
            "mfcc_std": mfcc.std(axis=0).tolist(),
            "mfcc_delta_mean": np.diff(mfcc, axis=0).mean(axis=0).tolist() if mfcc.shape[0] > 1 else [0] * self.N_MFCC,
            "spectral_centroid": spectral["centroid"],
            "spectral_bandwidth": spectral["bandwidth"],
            "spectral_rolloff": spectral["rolloff"],
            "zero_crossing_rate": spectral["zcr"],
            "pitch_mean": prosodic["pitch_mean"],
            "pitch_std": prosodic["pitch_std"],
            "energy_mean": prosodic["energy_mean"],
            "energy_std": prosodic["energy_std"],
        }

    def compute_voice_embedding(self, features: Dict) -> List[float]:
        """
        Compute a 128-dimensional voice embedding from extracted features.

        Concatenates and projects voice features into a fixed-size embedding.
        """
        if not features.get("valid"):
            return [0.0] * self.EMBEDDING_DIM

        # Collect feature vector components
        components = []

        # MFCCs (20 mean + 20 std + 20 delta = 60 dims)
        components.extend(features.get("mfcc_mean", [0] * self.N_MFCC))
        components.extend(features.get("mfcc_std", [0] * self.N_MFCC))
        components.extend(features.get("mfcc_delta_mean", [0] * self.N_MFCC))

        # Spectral features (4 dims)
        components.append(features.get("spectral_centroid", 0) / 8000.0)
        components.append(features.get("spectral_bandwidth", 0) / 4000.0)
        components.append(features.get("spectral_rolloff", 0) / 8000.0)
        components.append(features.get("zero_crossing_rate", 0))

        # Prosodic features (4 dims)
        components.append(features.get("pitch_mean", 0) / 500.0)
        components.append(features.get("pitch_std", 0) / 200.0)
        components.append(features.get("energy_mean", 0))
        components.append(features.get("energy_std", 0))

        # Pad/truncate to EMBEDDING_DIM
        arr = np.array(components[:self.EMBEDDING_DIM], dtype=np.float64)
        if len(arr) < self.EMBEDDING_DIM:
            arr = np.pad(arr, (0, self.EMBEDDING_DIM - len(arr)))

        # L2 normalize
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm

        return arr.tolist()

    def match_voice(
        self,
        embedding: List[float],
        database_embeddings: List[Dict],
        threshold: float = 0.70,
    ) -> List[Dict]:
        """Match a voice embedding against stored voiceprints."""
        query = np.array(embedding, dtype=np.float64)
        query_norm = np.linalg.norm(query)
        if query_norm > 0:
            query = query / query_norm

        matches = []
        for entry in database_embeddings:
            db_emb = np.array(entry["embedding"], dtype=np.float64)
            db_norm = np.linalg.norm(db_emb)
            if db_norm > 0:
                db_emb = db_emb / db_norm
            similarity = float(np.dot(query, db_emb))
            if similarity >= threshold:
                matches.append({
                    "visitor_id": entry.get("visitor_id"),
                    "similarity": round(similarity, 4),
                })

        matches.sort(key=lambda m: m["similarity"], reverse=True)
        return matches

    def detect_voice_liveness(self, audio_path: str) -> Dict:
        """
        Detect if audio is from a live speaker or a replay/synthetic attack.

        Checks for:
        - Natural pitch variation (live speakers have micro-variations)
        - Background noise consistency
        - Spectral characteristics of replayed audio
        """
        try:
            audio = self._load_audio(audio_path)
        except Exception as e:
            return {"is_live": False, "confidence": 0.0, "error": str(e)}

        scores = {}

        # 1. Pitch micro-variation (live voices have natural jitter)
        features = self._prosodic_features(audio)
        pitch_variation = features["pitch_std"]
        # Replayed audio typically has very low or very high pitch std
        if 5 < pitch_variation < 100:
            scores["pitch_naturalness"] = 0.8
        elif pitch_variation > 100:
            scores["pitch_naturalness"] = 0.3  # Possibly synthetic
        else:
            scores["pitch_naturalness"] = 0.4  # Too uniform (replay)

        # 2. Dynamic range (live audio has wider dynamic range)
        rms = np.sqrt(np.mean(audio ** 2))
        peak = np.max(np.abs(audio))
        crest_factor = peak / (rms + 1e-10)
        scores["dynamic_range"] = min(1.0, crest_factor / 10.0)

        # 3. High-frequency content (replayed audio loses high frequencies)
        fft_result = np.abs(np.fft.rfft(audio))
        high_freq_energy = np.mean(fft_result[len(fft_result) // 2:])
        low_freq_energy = np.mean(fft_result[:len(fft_result) // 2]) + 1e-10
        hf_ratio = high_freq_energy / low_freq_energy
        scores["high_freq_presence"] = min(1.0, hf_ratio * 5)

        # 4. Spectral flatness (noise-like vs tonal)
        geo_mean = np.exp(np.mean(np.log(fft_result + 1e-10)))
        arith_mean = np.mean(fft_result) + 1e-10
        spectral_flatness = geo_mean / arith_mean
        scores["spectral_naturalness"] = 1.0 - min(1.0, spectral_flatness * 2)

        # Ensemble
        overall = (
            0.3 * scores["pitch_naturalness"]
            + 0.25 * scores["dynamic_range"]
            + 0.25 * scores["high_freq_presence"]
            + 0.2 * scores["spectral_naturalness"]
        )

        return {
            "is_live": overall > 0.5,
            "confidence": round(overall, 4),
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "attack_type": None if overall > 0.5 else "replay_or_synthetic",
        }

    def _load_audio(self, path: str) -> np.ndarray:
        """Load audio file as float32 array."""
        if HAS_SCIPY:
            sr, audio = wavfile.read(path)
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0
            elif audio.dtype == np.int32:
                audio = audio.astype(np.float32) / 2147483648.0
            # Convert stereo to mono
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
            # Resample if needed (simple decimation)
            if sr != self.SAMPLE_RATE:
                ratio = self.SAMPLE_RATE / sr
                indices = np.arange(0, len(audio), 1 / ratio).astype(int)
                indices = indices[indices < len(audio)]
                audio = audio[indices]
            return audio
        else:
            # Fallback: read raw bytes
            with open(path, "rb") as f:
                raw = f.read()
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            return audio

    def _spectral_features(self, audio: np.ndarray) -> Dict:
        """Compute spectral features."""
        magnitude = np.abs(np.fft.rfft(audio, n=self.N_FFT))
        freqs = np.fft.rfftfreq(self.N_FFT, d=1.0 / self.SAMPLE_RATE)

        total = np.sum(magnitude) + 1e-10
        centroid = float(np.sum(freqs * magnitude) / total)
        bandwidth = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * magnitude) / total))
        cumsum = np.cumsum(magnitude)
        rolloff = float(freqs[np.searchsorted(cumsum, 0.85 * cumsum[-1])]) if len(cumsum) > 0 else 0

        # Zero crossing rate
        signs = np.sign(audio)
        zcr = float(np.mean(np.abs(np.diff(signs))) / 2)

        return {"centroid": centroid, "bandwidth": bandwidth, "rolloff": rolloff, "zcr": zcr}

    def _prosodic_features(self, audio: np.ndarray) -> Dict:
        """Extract prosodic features (pitch, energy)."""
        # Simple autocorrelation-based pitch detection
        frame_size = self.N_FFT
        hop = self.HOP_LENGTH
        num_frames = max(1, (len(audio) - frame_size) // hop)

        pitches = []
        energies = []

        for i in range(num_frames):
            start = i * hop
            frame = audio[start: start + frame_size]
            if len(frame) < frame_size:
                break

            # Energy
            energies.append(float(np.sqrt(np.mean(frame ** 2))))

            # Autocorrelation pitch
            corr = np.correlate(frame, frame, mode="full")
            corr = corr[len(corr) // 2:]
            # Find first peak after minimum
            if len(corr) > 30:
                d = np.diff(corr[:len(corr) // 2])
                try:
                    start_idx = np.where(d > 0)[0][0]
                    peak = start_idx + np.argmax(corr[start_idx: start_idx + 200])
                    if peak > 0:
                        pitches.append(self.SAMPLE_RATE / peak)
                except (IndexError, ValueError):
                    pass

        return {
            "pitch_mean": float(np.mean(pitches)) if pitches else 0.0,
            "pitch_std": float(np.std(pitches)) if pitches else 0.0,
            "energy_mean": float(np.mean(energies)) if energies else 0.0,
            "energy_std": float(np.std(energies)) if energies else 0.0,
        }


voice_service = VoiceRecognitionService()
