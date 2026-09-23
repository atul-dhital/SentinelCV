"""
Run this once before production deployment to generate all required secrets.
Output the values and paste them into .env.production.

Usage:
    python scripts/generate_secrets.py
"""
import secrets
import base64
import hashlib


def gen_hex(n: int) -> str:
    return secrets.token_hex(n)


def gen_urlsafe(n: int) -> str:
    return secrets.token_urlsafe(n)


print("=" * 60)
print("SentinelCV — Generated Secrets")
print("Paste these into .env.production — store originals in a")
print("password manager (1Password, Bitwarden, AWS Secrets Manager)")
print("=" * 60)
print()
print(f"SECRET_KEY={gen_hex(64)}")
print(f"INTERNAL_SERVICE_KEY={gen_hex(32)}")
print(f"REDIS_PASSWORD={gen_urlsafe(24)}")
print(f"DB_PASSWORD={gen_urlsafe(24)}")
print(f"GRAFANA_PASSWORD={gen_urlsafe(20)}")
print()
print("# Copy the DB_PASSWORD value above into DATABASE_URL:")
print("# DATABASE_URL=postgresql://sentinelcv:<DB_PASSWORD>@postgres:5432/sentinelcv_prod")
print("# REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379/0")
