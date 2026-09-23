from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"

for candidate in (PROJECT_ROOT, BACKEND_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


def _encode_frame(frame) -> str:
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), 88],
    )
    if not ok:
        raise RuntimeError("Failed to encode webcam frame.")
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


def _detect_face_focus(frame, face_cascade: cv2.CascadeClassifier | None):
    if face_cascade is not None:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(48, 48),
        )
        if faces is not None and len(faces) > 0:
            x, y, width, height = max(faces, key=lambda rect: rect[2] * rect[3])
            pad_x = int(width * 0.45)
            pad_top = int(height * 0.65)
            pad_bottom = int(height * 0.45)
            x0 = max(0, x - pad_x)
            y0 = max(0, y - pad_top)
            x1 = min(frame.shape[1], x + width + pad_x)
            y1 = min(frame.shape[0], y + height + pad_bottom)
            focused = frame[y0:y1, x0:x1]
            if focused.size != 0:
                return focused

    frame_height, frame_width = frame.shape[:2]
    crop_ratio = 0.72
    crop_width = max(1, int(frame_width * crop_ratio))
    crop_height = max(1, int(frame_height * crop_ratio))
    x0 = max(0, (frame_width - crop_width) // 2)
    y0 = max(0, (frame_height - crop_height) // 2)
    return frame[y0 : y0 + crop_height, x0 : x0 + crop_width]


def capture_frames(args: argparse.Namespace) -> None:
    backend = getattr(cv2, "CAP_DSHOW", 0) if os.name == "nt" else 0
    capture = cv2.VideoCapture(args.camera_index, backend)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open webcam index {args.camera_index}.")

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    face_cascade = cv2.CascadeClassifier(
        f"{cv2.data.haarcascades}haarcascade_frontalface_default.xml"
    )
    if face_cascade.empty():
        face_cascade = None

    try:
        warmup_frames = max(5, args.warmup_frames)
        for _ in range(warmup_frames):
            capture.read()
            time.sleep(0.03)

        captured_frames: list[str] = []
        next_capture_at = time.monotonic()
        deadline = time.monotonic() + (args.duration_ms / 1000.0)

        while time.monotonic() <= deadline and len(captured_frames) < args.max_frames:
            ok, frame = capture.read()
            if not ok:
                continue

            if time.monotonic() < next_capture_at:
                continue

            focused = _detect_face_focus(frame, face_cascade) if args.face_focus else frame
            resized = cv2.resize(focused, (args.width, args.height), interpolation=cv2.INTER_AREA)
            captured_frames.append(_encode_frame(resized))
            next_capture_at = time.monotonic() + (args.interval_ms / 1000.0)

        if not captured_frames:
            raise RuntimeError("No frames were captured from the webcam.")

        payload = {
            "frame_count": len(captured_frames),
            "frames": captured_frames,
        }
        Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    finally:
        capture.release()


def create_visitor_log(args: argparse.Namespace) -> None:
    from db.base import SessionLocal
    from models.models import User, VisitorLog

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email).first()
        if user is None:
            raise RuntimeError(f"No user found for email {args.email!r}.")

        visitor_log = VisitorLog(
            organization_id=user.organization_id,
            confidence=args.confidence,
            identified=False,
            status=args.status,
            source_video=args.source_video,
        )
        db.add(visitor_log)
        db.commit()
        db.refresh(visitor_log)

        print(
            json.dumps(
                {
                    "visitor_log_id": str(visitor_log.id),
                    "organization_id": str(user.organization_id),
                }
            )
        )
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Helper utilities for local SentinelCV liveness checks.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture-frames", help="Capture focused webcam frames to a JSON file.")
    capture_parser.add_argument("--output", required=True)
    capture_parser.add_argument("--camera-index", type=int, default=0)
    capture_parser.add_argument("--duration-ms", type=int, required=True)
    capture_parser.add_argument("--interval-ms", type=int, required=True)
    capture_parser.add_argument("--max-frames", type=int, required=True)
    capture_parser.add_argument("--width", type=int, default=320)
    capture_parser.add_argument("--height", type=int, default=240)
    capture_parser.add_argument("--warmup-frames", type=int, default=8)
    capture_parser.add_argument("--face-focus", action="store_true", default=True)
    capture_parser.set_defaults(func=capture_frames)

    create_log_parser = subparsers.add_parser("create-visitor-log", help="Create a temporary visitor log for a local liveness test.")
    create_log_parser.add_argument("--email", required=True)
    create_log_parser.add_argument("--status", default="detected")
    create_log_parser.add_argument("--confidence", type=float, default=0.5)
    create_log_parser.add_argument("--source-video", default="live_liveness_local_test")
    create_log_parser.set_defaults(func=create_visitor_log)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())