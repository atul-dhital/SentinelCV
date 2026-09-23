import logging
import os
from pathlib import Path
from typing import Optional

from core.paths import DATA_DIR

logger = logging.getLogger("sentinelcv.storage")


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return default


class StorageProvider:
    """Persist media locally with optional S3-compatible replication.

    The rest of the app still expects a writable local path for AI processing,
    validation, and auth-gated `/static` reads. When object storage is enabled,
    files are therefore written to the local data directory first and then
    replicated to the configured bucket.
    """

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or DATA_DIR)
        configured_type = (os.getenv("STORAGE_TYPE") or "").strip().lower()
        self.storage_type = configured_type or ("r2" if _first_env("R2_BUCKET", "OBJECT_STORAGE_BUCKET") else "local")
        self.bucket = _first_env("OBJECT_STORAGE_BUCKET", "R2_BUCKET", "AWS_S3_BUCKET")
        self.endpoint_url = _first_env("OBJECT_STORAGE_ENDPOINT_URL", "R2_ENDPOINT_URL", "AWS_S3_ENDPOINT_URL")
        self.region = _first_env("OBJECT_STORAGE_REGION", "R2_REGION", "AWS_S3_REGION", default="auto")
        self.prefix = _first_env("OBJECT_STORAGE_PREFIX", "R2_PREFIX", "AWS_S3_PREFIX")
        self.public_base_url = _first_env(
            "OBJECT_STORAGE_PUBLIC_BASE_URL",
            "R2_PUBLIC_BASE_URL",
            "R2_PUBLIC_DEV_URL",
            "AWS_S3_PUBLIC_BASE_URL",
        ).rstrip("/")
        self.access_key_id = _first_env("OBJECT_STORAGE_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID")
        self.secret_access_key = _first_env(
            "OBJECT_STORAGE_SECRET_ACCESS_KEY",
            "R2_SECRET_ACCESS_KEY",
            "AWS_SECRET_ACCESS_KEY",
        )
        self._s3_client = None
        self._remote_enabled = self.storage_type in {"s3", "r2"}

        if self._remote_enabled:
            missing = []
            if not self.bucket:
                missing.append("bucket")
            if not self.endpoint_url:
                missing.append("endpoint_url")
            if not self.access_key_id:
                missing.append("access_key_id")
            if not self.secret_access_key:
                missing.append("secret_access_key")
            if missing:
                logger.warning(
                    "Object storage requested (STORAGE_TYPE=%s) but configuration is incomplete (%s). Falling back to local-only storage.",
                    self.storage_type,
                    ", ".join(missing),
                )
                self._remote_enabled = False

    def _normalize_relative_path(self, relative_path: str) -> str:
        cleaned = str(relative_path or "").replace("\\", "/").strip().lstrip("/")
        if not cleaned or cleaned in {".", ".."} or cleaned.startswith("../") or "/../" in cleaned:
            raise ValueError("Invalid storage path")
        return cleaned

    def _object_key(self, relative_path: str) -> str:
        normalized = self._normalize_relative_path(relative_path)
        if not self.prefix:
            return normalized
        return f"{self.prefix.rstrip('/')}/{normalized}"

    def _delete_local_path(self, full_path: Path) -> None:
        try:
            if full_path.exists():
                full_path.unlink()
        except OSError:
            logger.warning("Failed to remove local storage file %s", full_path, exc_info=True)

    def _get_s3_client(self):
        if not self._remote_enabled:
            return None
        if self._s3_client is not None:
            return self._s3_client

        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - dependency issue
            raise RuntimeError(
                "Object storage is enabled but boto3 is not installed. Install backend dependencies again."
            ) from exc

        self._s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region or "auto",
        )
        return self._s3_client

    def get_full_path(self, relative_path: str) -> Path:
        """Resolve a repo-relative storage path inside the local data cache."""
        return self.data_dir / self._normalize_relative_path(relative_path)

    def has_remote_storage(self) -> bool:
        return self._remote_enabled

    def save_file(self, relative_path: str, content: bytes, *, content_type: Optional[str] = None) -> Path:
        """Save bytes locally and optionally replicate them to object storage."""
        full_path = self.get_full_path(relative_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)

        if not self._remote_enabled:
            return full_path

        client = self._get_s3_client()
        try:
            client.put_object(
                Bucket=self.bucket,
                Key=self._object_key(relative_path),
                Body=content,
                ContentType=content_type or "application/octet-stream",
            )
        except Exception as exc:
            self._delete_local_path(full_path)
            raise RuntimeError(f"Failed to upload '{relative_path}' to object storage") from exc

        return full_path

    def ensure_local_file(self, relative_path: str) -> Path:
        """Return a local path, downloading from object storage if necessary."""
        full_path = self.get_full_path(relative_path)
        if full_path.exists():
            return full_path
        if not self._remote_enabled:
            raise FileNotFoundError(relative_path)

        full_path.parent.mkdir(parents=True, exist_ok=True)
        client = self._get_s3_client()
        try:
            client.download_file(self.bucket, self._object_key(relative_path), str(full_path))
        except Exception as exc:
            self._delete_local_path(full_path)
            raise FileNotFoundError(relative_path) from exc
        return full_path

    def delete_file(self, relative_path: str) -> None:
        """Delete a file from the local cache and object storage when configured."""
        full_path = self.get_full_path(relative_path)
        self._delete_local_path(full_path)

        if not self._remote_enabled:
            return

        client = self._get_s3_client()
        try:
            client.delete_object(Bucket=self.bucket, Key=self._object_key(relative_path))
        except Exception:
            logger.warning("Failed to delete remote object for %s", relative_path, exc_info=True)

    def get_public_url(self, relative_path: str) -> Optional[str]:
        if not self.public_base_url:
            return None
        normalized = self._normalize_relative_path(relative_path)
        return f"{self.public_base_url}/{normalized}"


storage = StorageProvider()
