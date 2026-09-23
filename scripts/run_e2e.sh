#!/usr/bin/env bash
# ============================================================
# SentinelCV E2E Test Runner
#
# Starts a complete isolated stack via docker-compose.e2e.yml,
# runs all Playwright specs, then tears down.
#
# Usage:
#   ./scripts/run_e2e.sh              # run all specs
#   ./scripts/run_e2e.sh auth.spec.ts # run one spec
#   ./scripts/run_e2e.sh --ui         # interactive Playwright UI
#
# Requirements:
#   - Docker + Compose V2 (docker compose, not docker-compose)
#   - Node.js ≥ 20  (for Playwright runner on host)
#   - npm ci already run in frontend/
# ============================================================

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="docker compose -f $ROOT/docker-compose.e2e.yml"
SPEC="${1:-}"
MAX_WAIT=120   # seconds

log() { echo "[e2e] $*"; }
die() { echo "[e2e] ERROR: $*" >&2; exit 1; }

cleanup() {
    log "Tearing down E2E stack..."
    $COMPOSE down --remove-orphans --volumes 2>/dev/null || true
}
trap cleanup EXIT

# ── 1. Build and start the E2E stack ──────────────────────────────────────
log "Building images..."
$COMPOSE build --quiet

log "Starting E2E stack (postgres-e2e, backend-e2e, seed-e2e, frontend-e2e)..."
$COMPOSE up -d

# ── 2. Wait for services ───────────────────────────────────────────────────
log "Waiting for backend (http://localhost:8000/health)..."
waited=0
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    sleep 2; waited=$((waited + 2))
    [ $waited -gt $MAX_WAIT ] && die "Backend did not become healthy within ${MAX_WAIT}s"
done
log "Backend healthy."

log "Waiting for frontend (http://localhost:3001)..."
waited=0
until curl -sf http://localhost:3001 > /dev/null 2>&1; do
    sleep 2; waited=$((waited + 2))
    [ $waited -gt $MAX_WAIT ] && die "Frontend did not become healthy within ${MAX_WAIT}s"
done
log "Frontend healthy."

# ── 3. Install Playwright browsers if needed ──────────────────────────────
cd "$ROOT/frontend"
if ! npx playwright --version > /dev/null 2>&1; then
    log "Installing @playwright/test..."
    npm ci
fi
log "Ensuring Playwright Chromium is installed..."
npx playwright install --with-deps chromium

# ── 4. Run E2E tests ──────────────────────────────────────────────────────
log "Running Playwright E2E tests..."
EXIT_CODE=0

E2E_EXTERNAL=1 \
E2E_BASE_URL=http://localhost:3001 \
E2E_BACKEND_URL=http://localhost:8000 \
E2E_ADMIN_EMAIL=admin@test.com \
E2E_ADMIN_PASS=Admin123! \
E2E_STAFF_EMAIL=staff@test.com \
E2E_STAFF_PASS=Staff123! \
    npx playwright test $SPEC || EXIT_CODE=$?

# ── 5. Report ──────────────────────────────────────────────────────────────
if [ $EXIT_CODE -eq 0 ]; then
    log "All E2E tests passed ✓"
else
    log "E2E tests FAILED. Run 'npm run e2e:report' in frontend/ to view the HTML report."
fi

exit $EXIT_CODE
