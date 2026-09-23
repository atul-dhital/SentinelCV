"""Runtime helper to load encrypted .env settings before app initialization.

This module supports US-DEP-004 by allowing deployments to keep secrets in an
encrypted env file and decrypt them at startup time.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("sentinelcv.env_loader")


def _parse_env_content(raw_text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _read_encryption_key() -> bytes | None:
    key_value = os.getenv("SENTINELCV_ENV_KEY", "").strip()
    if key_value:
        return key_value.encode("utf-8")

    key_file = os.getenv("SENTINELCV_ENV_KEY_FILE", "").strip()
    if key_file:
        path = Path(key_file)
        if path.exists():
            return path.read_text(encoding="utf-8").strip().encode("utf-8")

    return None


def load_encrypted_env_file() -> bool:
    """Load encrypted env values into process environment.

    Returns True when encrypted variables were loaded, otherwise False.
    """
    encrypted_path = os.getenv("SENTINELCV_ENCRYPTED_ENV_FILE", "").strip()
    if not encrypted_path:
        return False

    file_path = Path(encrypted_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Encrypted env file not found: {file_path}")

    key_bytes = _read_encryption_key()
    if not key_bytes:
        raise ValueError(
            "Encrypted env file configured but no key provided. "
            "Set SENTINELCV_ENV_KEY or SENTINELCV_ENV_KEY_FILE."
        )

    encrypted_data = file_path.read_bytes()
    try:
        decrypted_data = Fernet(key_bytes).decrypt(encrypted_data).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt env file: invalid key or corrupted file.") from exc

    parsed = _parse_env_content(decrypted_data)
    for key, value in parsed.items():
        # Keep explicitly provided process env values as highest precedence.
        os.environ.setdefault(key, value)

    logger.info("Loaded %d variables from encrypted env file", len(parsed))
    return True
