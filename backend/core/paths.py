import os


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BACKEND_DIR, "data"))
FACE_IMAGE_DIR = os.path.join(DATA_DIR, "face_images")
RAW_VIDEO_DIR = os.path.join(DATA_DIR, "raw_videos")

_DATA_DIR_REAL = os.path.realpath(DATA_DIR)


def data_path(relative_path: str) -> str:
    """Resolve relative_path under DATA_DIR.

    Raises ValueError if the resolved path would escape DATA_DIR — catches
    absolute paths, drive letters, UNC paths, `..` traversal, and symlinks
    pointing outside, regardless of how the input was written.
    """
    cleaned = relative_path.lstrip("/\\")
    candidate = os.path.realpath(os.path.join(DATA_DIR, cleaned))
    if os.path.commonpath([candidate, _DATA_DIR_REAL]) != _DATA_DIR_REAL:
        raise ValueError(f"Path escapes DATA_DIR: {relative_path!r}")
    return candidate
