#!/usr/bin/env bash
# Production startup script for SentinelCV.
# Run this instead of `docker compose up` directly on first deploy
# and after any migration-bearing release.
#
# Usage:
#   chmod +x scripts/start_production.sh
#   ./scripts/start_production.sh

set -euo pipefail

COMPOSE="docker compose -f docker-compose.prod.yml"

# ── 1. Pre-flight: verify all required env vars are present ───────────────────
echo "==> Checking required environment variables..."
REQUIRED=(SECRET_KEY DB_PASSWORD REDIS_PASSWORD INTERNAL_SERVICE_KEY FRONTEND_URL NEXT_PUBLIC_API_URL GRAFANA_PASSWORD)
MISSING=()
for var in "${REQUIRED[@]}"; do
  val="${!var:-}"
  if [[ -z "$val" || "$val" == CHANGE_ME* ]]; then
    MISSING+=("$var")
  fi
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "ERROR: The following required variables are missing or still have placeholder values:"
  for var in "${MISSING[@]}"; do echo "  - $var"; done
  echo ""
  echo "Run: python scripts/generate_secrets.py"
  echo "Then fill in .env.production and export the vars (or use --env-file)."
  exit 1
fi
echo "    All required variables present."

# ── 2. Start only the database first ─────────────────────────────────────────
echo ""
echo "==> Starting PostgreSQL..."
$COMPOSE up -d postgres

echo "    Waiting for PostgreSQL to become healthy..."
until $COMPOSE ps postgres | grep -q "healthy"; do
  sleep 2
  echo -n "."
done
echo ""
echo "    PostgreSQL is healthy."

# ── 3. Enable pgvector extension ─────────────────────────────────────────────
echo ""
echo "==> Enabling pgvector extension..."
$COMPOSE exec -T postgres psql -U sentinelcv -d sentinelcv_prod \
  -c "CREATE EXTENSION IF NOT EXISTS vector;" \
  && echo "    pgvector ready."

# ── 4. Run Alembic migrations ────────────────────────────────────────────────
echo ""
echo "==> Running database migrations..."
$COMPOSE run --rm backend alembic upgrade head
echo "    Migrations complete."

# ── 5. Verify migration state ─────────────────────────────────────────────────
echo ""
echo "==> Current migration revision:"
$COMPOSE run --rm backend alembic current

# ── 6. Start remaining services ───────────────────────────────────────────────
echo ""
echo "==> Starting all services..."
$COMPOSE up -d

# ── 7. Wait for backend health ────────────────────────────────────────────────
echo ""
echo "    Waiting for backend to become healthy..."
RETRIES=30
until $COMPOSE ps backend | grep -q "healthy" || [[ $RETRIES -eq 0 ]]; do
  sleep 3
  RETRIES=$((RETRIES - 1))
  echo -n "."
done
echo ""

if [[ $RETRIES -eq 0 ]]; then
  echo "ERROR: Backend did not become healthy in time. Check logs:"
  echo "  $COMPOSE logs backend --tail=50"
  exit 1
fi

echo ""
echo "========================================="
echo "SentinelCV is running."
echo "  API:     https://\$FRONTEND_URL/api/v1"
echo "  Grafana: http://localhost:3001"
echo "  Prometheus: http://localhost:9090"
echo "========================================="
$COMPOSE ps
