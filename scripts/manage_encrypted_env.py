#!/usr/bin/env python3
"""Utilities to manage encrypted production environment files.

Commands:
  - generate-key: creates a Fernet key and optionally stores it in a file
  - encrypt: encrypts a plaintext env file into a binary encrypted file
  - decrypt: decrypts encrypted env file into plaintext env file

Examples:
  python scripts/manage_encrypted_env.py generate-key --out .env.key
  python scripts/manage_encrypted_env.py encrypt --in .env.production --out .env.production.encrypted --key-file .env.key
  python scripts/manage_encrypted_env.py decrypt --in .env.production.encrypted --out .env.production --key-file .env.key
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def _read_key(key: str | None, key_file: Path | None, key_env: str | None) -> bytes:
    if key:
        return key.encode("utf-8")

    if key_file:
        return key_file.read_text(encoding="utf-8").strip().encode("utf-8")

    if key_env:
        value = os.getenv(key_env, "").strip()
        if value:
            return value.encode("utf-8")

    raise ValueError("No encryption key provided. Use --key, --key-file, or --key-env.")


def _chmod_owner_read_only(path: Path) -> None:
    if os.name == "nt":
        # Windows ACL handling is environment-specific; keep file hidden from accidental reads by location.
        return
    path.chmod(stat.S_IRUSR)


def generate_key(output: Path | None) -> int:
    key = Fernet.generate_key().decode("utf-8")
    print(key)

    if output:
        output.write_text(key + "\n", encoding="utf-8")
        _chmod_owner_read_only(output)
        print(f"Saved key to {output}")

    return 0


def encrypt_file(source: Path, target: Path, key_bytes: bytes) -> int:
    if not source.exists():
        raise FileNotFoundError(f"Input file not found: {source}")

    fernet = Fernet(key_bytes)
    plaintext = source.read_bytes()
    encrypted = fernet.encrypt(plaintext)
    target.write_bytes(encrypted)
    _chmod_owner_read_only(target)

    print(f"Encrypted {source} -> {target}")
    return 0


def decrypt_file(source: Path, target: Path, key_bytes: bytes) -> int:
    if not source.exists():
        raise FileNotFoundError(f"Input file not found: {source}")

    fernet = Fernet(key_bytes)
    encrypted = source.read_bytes()

    try:
        plaintext = fernet.decrypt(encrypted)
    except InvalidToken as exc:
        raise ValueError("Invalid key or corrupted encrypted file.") from exc

    target.write_bytes(plaintext)
    _chmod_owner_read_only(target)
    print(f"Decrypted {source} -> {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage encrypted SentinelCV .env files")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gen = subparsers.add_parser("generate-key", help="Generate a Fernet key")
    gen.add_argument("--out", type=Path, help="Optional path to save generated key")

    enc = subparsers.add_parser("encrypt", help="Encrypt env file")
    enc.add_argument("--in", dest="source", type=Path, required=True, help="Plaintext env file")
    enc.add_argument("--out", dest="target", type=Path, required=True, help="Encrypted file path")
    enc.add_argument("--key", help="Encryption key value")
    enc.add_argument("--key-file", type=Path, help="Path to key file")
    enc.add_argument("--key-env", default="SENTINELCV_ENV_KEY", help="Environment variable containing key")

    dec = subparsers.add_parser("decrypt", help="Decrypt env file")
    dec.add_argument("--in", dest="source", type=Path, required=True, help="Encrypted env file")
    dec.add_argument("--out", dest="target", type=Path, required=True, help="Plaintext env file path")
    dec.add_argument("--key", help="Encryption key value")
    dec.add_argument("--key-file", type=Path, help="Path to key file")
    dec.add_argument("--key-env", default="SENTINELCV_ENV_KEY", help="Environment variable containing key")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "generate-key":
            return generate_key(args.out)

        key_bytes = _read_key(args.key, args.key_file, args.key_env)

        if args.command == "encrypt":
            return encrypt_file(args.source, args.target, key_bytes)

        if args.command == "decrypt":
            return decrypt_file(args.source, args.target, key_bytes)

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
