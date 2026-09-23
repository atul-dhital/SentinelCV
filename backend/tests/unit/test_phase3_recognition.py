"""Unit tests for Phase 3 recognition engines."""

from datetime import datetime, timedelta, timezone
import numpy as np

from services.phase3_recognition_engines import (
    ActionClassifier,
    AngleClassifier,
    BehavioralTrajectory,
    EmotionActionDetector,
    EmotionClassifier,
    MultiAngleRecognitionEngine,
    TemporalConsistencyTracker,
)


class _FakeViT:
    def extract_embedding(self, image_path, normalize=True):
        return [0.1, 0.2, 0.3]

    def compare_embeddings(self, a, b):
        return 0.9


def test_angle_classifier_frontal():
    angle, confidence = AngleClassifier.classify(0.0, 0.0)
    assert angle == "frontal"
    assert confidence >= 0.8


def test_angle_classifier_profile_left():
    angle, confidence = AngleClassifier.classify(-70.0, 0.0)
    assert angle == "profile_left"
    assert confidence >= 0.5


def test_multi_angle_set_completeness():
    engine = MultiAngleRecognitionEngine(_FakeViT())
    angle_data = {
        "frontal": {"image_path": "/tmp/face.jpg", "yaw": 0.0, "pitch": 0.0},
        "profile_left": {"image_path": "/tmp/face.jpg", "yaw": -70.0, "pitch": 0.0},
    }
    result = engine.create_multi_angle_set("visitor_1", angle_data)

    assert result is not None
    assert result.visitor_id == "visitor_1"
    assert result.completeness == 2 / 7


def test_temporal_tracker_prunes_old_events():
    tracker = TemporalConsistencyTracker(history_window=60)
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    tracker.record_sighting("visitor_1", "cam_old", old_time, 0.7)
    assert tracker.get_recent_cameras("visitor_1") == []


def test_detect_emotion_accepts_numpy_arrays():
    detector = EmotionActionDetector()

    emotion, confidence = detector.detect_emotion(np.array([0.1, -0.2, 0.3]))

    assert isinstance(emotion, EmotionClassifier)
    assert 0.0 <= confidence <= 1.0


def test_compute_engagement_counts_smile_actions():
    detector = EmotionActionDetector()
    trajectory = BehavioralTrajectory(
        visitor_id="visitor-1",
        window_seconds=300,
        emotions={"happy": [(1.0, 0.9)]},
        actions={ActionClassifier.SMILE.value: [(1.0, 0.8)]},
        engagement_score=0.0,
    )

    engagement = detector.compute_engagement(trajectory)

    assert engagement > 0
