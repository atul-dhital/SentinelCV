# SentinelCV — Agent / AI Coding Assistant Guide

## Start of Session Checklist

1. Read `docs/project-truth/SESSION_HANDOFF.md` — canonical runtime state, known risks, route truth.
2. Read `docs/project-truth/README.md` — documentation index.
3. Verify route mounts in `backend/main.py` before touching any API family.
4. Verify frontend API contract in `frontend/src/services/api.ts` before editing callers.

## Agent Operating Rules

- **Use the todo tool**: create or update a short plan with `manage_todo_list` at the start of any multi-step task.
- **Preamble for tool calls**: before making external or repo-changing tool calls, send a one-line preamble describing the next action.
- **Progress cadence**: give a concise progress update after 3–5 tool calls or when editing more than three files in a burst.
- **Keep instructions minimal**: link to detailed docs under `docs/project-truth/` rather than duplicating them.

## Canonical Source of Truth

| Topic | File |
|-------|------|
| Route mounts | `backend/main.py` |
| ORM models | `backend/models/models.py` |
| API schemas | `backend/schemas/schemas.py` |
| Auth/session | `backend/api/auth.py`, `frontend/src/lib/authSession.ts` |
| Frontend API contract | `frontend/src/services/api.ts` |
| Architecture docs | `docs/project-truth/` |

Skills index: see `.github/skills/README.md` for a quick skill catalog and links to `SKILL.md` descriptors.

> `doc/` (no 's') is historical background only — do not treat as current truth.

## Security Rules

- **Never remove auth** from any route without explicit instruction.
- `POST /api/v1/logs/` requires `X-Internal-API-Key` (AI service ingestion).
- `POST /api/v1/notifications/` requires `X-Internal-API-Key`.
- `POST /api/v1/visitors/search` requires `X-Internal-API-Key`.
- `/metrics` requires `METRICS_TOKEN` bearer or `X-Metrics-Token` when `METRICS_TOKEN` env var is set.
- `ENFORCE_TENANT_FILTER` defaults **on** — set `ENFORCE_TENANT_FILTER=0` only in test environments, never in production.
- Operator routes bypassing the tenant filter must use `execution_options(skip_tenant_filter=True)`.

## Duplicate Surfaces — Read Before Editing

| Domain | File A | File B | Rule |
|--------|--------|--------|------|
| GDPR | `api/compliance.py` | `api/gdpr_api.py` | Verify which surface the task targets |
| SSO | `api/sso.py` (legacy OAuth) | `api/sso_api.py` (SAML) | Different auth flows — do not merge assumptions |
| Camera | `api/camera.py` (live session) | `api/cameras.py` (registry) | Separate route families |

## Experimental / Phase 3 Features

Phase 3 scaffold routers are mounted only when `ENABLE_PHASE3_FEATURES=1`.
Files to treat as experimental (not production-hardened):
- `backend/api/phase3_complete_api_scaffold.py`
- `backend/api/federated_learning.py`
- `backend/api/three_d_face.py`
- `backend/api/multimodal.py`
- `backend/api/vision_transformers.py`
- `backend/api/advanced_recognition.py`
- `backend/api/future_enhancements.py`

## Database Rules

- SQLite fallback is for local dev only — `SENTINELCV_ALLOW_SQLITE_FALLBACK` defaults on in non-production.
- SQLite stores embeddings as encrypted JSON; PostgreSQL uses `Vector(512)` — behavior differs.
- Schema changes require an Alembic migration. Do not rely on `AUTO_INIT_DB` in production.
- Update `docs/project-truth/database-schema.md` when models change.

## Performance & Architecture Status (June 8, 2026)

### Implemented Optimizations ✅

| Optimization | Status | Details |
|--------------|--------|---------|
| **N+1 Query Prevention** | ✅ COMPLETE | 43 Organization relationships use `lazy="raise"` |
| **Query Memory Bounds** | ✅ COMPLETE | 110 ORM queries bounded with `.limit()` (100K-500K rows) |
| **WebSocket Memory Leak** | ✅ COMPLETE | 1-hour TTL + automatic cleanup in `api/camera.py` |
| **SQL Safety** | ✅ COMPLETE | 2 raw SQL queries verified safe |
| **Frontend Modularization** | ✅ COMPLETE | 7 modular service files (~60% bundle reduction) |
| **Performance Testing** | ✅ COMPLETE | Memory profiling & latency infrastructure ready |

See `OPTIMIZATION_SUMMARY.md` and `FINAL_AUDIT_REPORT.md` for detailed metrics.

## Environment Variables Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | (none) | JWT signing — must be ≥32 chars in production |
| `EMBEDDING_KEY_SECRET` | (none) | Biometric encryption — must differ from SECRET_KEY |
| `INTERNAL_SERVICE_KEY` | (none) | Guards internal AI-service endpoints |
| `METRICS_TOKEN` | (none) | Guards /metrics — leave unset to keep open for local scraping |
| `ENFORCE_TENANT_FILTER` | `1` (on) | Global ORM tenant filter — disable only in tests |
| `ENABLE_PHASE3_FEATURES` | `0` (off) | Mounts all 11 experimental phase3 routers |
| `ENABLE_EMOTION_RECOGNITION`, `ENABLE_ACTION_RECOGNITION`, `ENABLE_CROSS_CAMERA_REID`, `ENABLE_MULTIMODAL`, `ENABLE_3D_FACE`, `ENABLE_FEDERATED_LEARNING`, `ENABLE_VIT_RECOGNITION`, `ENABLE_MULTISPECTRAL`, `ENABLE_MODEL_AB_TESTING`, `ENABLE_SYNTHETIC_DATA`, `ENABLE_TEMPORAL_AUGMENTATION`, `ENABLE_MOBILE_SYNC`, `ENABLE_ADVANCED_SECURITY` | `0` (off) each | Added 2026-07-28 (roadmap §10). Granular per-module flags — mounts just that module's router(s) without needing the coarse `ENABLE_EXPERIMENTAL_FEATURES`/`ENABLE_PHASE3_FEATURES` switch. See `GRANULAR_FEATURE_FLAGS` in `backend/main.py`. All are blocked in production by the same startup guard as the two coarse flags. Not every router has a 1:1 named flag (`training`, `learning`, `model_versioning`, legacy `sso`, `router_liveness_adv`, `router_edge`, `router_adv_analytics`, `router_integrations` stay under the coarse flags only — no roadmap-named equivalent exists for them). `ENABLE_VIT_RECOGNITION` gates *two* independent ViT surfaces (`vision_transformers.py` experimental-tier and `router_vit` phase3-tier) — a duplicate-route situation the same as camera/SSO/GDPR, not yet consolidated. Reported live at `GET /health/readiness` → `experimental_modules_enabled`. |
| `REDIS_URL` | (none) | Required for durable queues and rate limiting |
| `AI_SERVICE_URL` | `http://127.0.0.1:8001` | AI face recognition service |
| `SENTINELCV_ENV` | `development` | Set to `production` to enforce stricter checks |
| `SENTINELCV_STRICT_RECOGNITION` | `0` (off) | On the **AI service** process (`ai_services/face_engine.py`). When `1`, refuses the weak 32x32-grayscale fallback embedding outright instead of silently enrolling a non-discriminative "identity". Defaults to `1` in both prod docker-compose files. `backend/main.py` `/health/readiness` fails (not warns) in production when the AI service reports no real ArcFace/AdaFace backend, regardless of this flag. |