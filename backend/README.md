# SentinelCV Backend

This backend is a FastAPI application that provides the SentinelCV API, organization-scoped business logic, database models, reporting endpoints, and opt-in experimental feature surfaces.

## Layout

- `main.py`: FastAPI application entrypoint and route registration
- `api/`: HTTP routes grouped by feature area
- `services/`: business logic, model orchestration, queues, and integrations
- `models/`: SQLAlchemy models
- `schemas/`: Pydantic request and response schemas
- `db/`: database setup and session wiring
- `core/`: security, settings, paths, and shared runtime helpers
- `tests/`: integration and service-level verification
- `scripts/`: migrations, benchmarking, queue workers, and operational helpers

## Local Run

Install dependencies:

```powershell
cd backend
python -m pip install -r requirements.txt
```

Run the API:

```powershell
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open:

- API docs: `http://localhost:8000/docs`
- Readiness: `http://localhost:8000/health/readiness`

## Runtime Notes

- Default development database is SQLite.
- PostgreSQL enables pgvector-backed similarity search when configured.
- Background jobs fall back to in-process execution unless Redis queue mode is enabled.
- Redis-backed queue durability is used when a live Redis connection is available.
- Research modules are disabled by default. `ENABLE_EXPERIMENTAL_FEATURES=1` and `ENABLE_PHASE3_FEATURES=1` mount distinct experimental router sets; neither is allowed in production.

## ✅ Performance & Architecture Optimizations (June 2026)

- **N+1 Query Prevention**: All 43 Organization model relationships use `lazy="raise"` to prevent implicit loading.
- **Query Memory Bounds**: 110 ORM queries bounded with `.limit()` (100K-500K rows depending on entity type).
- **WebSocket Memory Leak Fix**: 1-hour session TTL with automatic cleanup in `api/camera.py`.
- **SQL Safety**: 2 raw SQL queries verified safe with proper bounds.
- **Frontend contract:** `frontend/src/services/api.ts` is the canonical client contract; helper service files coexist with the facade.
- **Performance Tests**: Infrastructure for memory profiling and latency testing in `scripts/performance_test.py`.

See `OPTIMIZATION_SUMMARY.md` and `FINAL_AUDIT_REPORT.md` for detailed metrics and verification.

## Queue Mode

Enable durable queue processing with Redis:

```powershell
$env:VIDEO_JOB_QUEUE_MODE="redis"
$env:REDIS_URL="redis://localhost:6379/0"
python scripts/video_queue_worker.py
```

The application will continue to work without Redis, but jobs will not be durable across process restarts.

## Tests

Run the full backend test suite:

```powershell
cd backend
python -m pytest
```

Run a focused slice:

```powershell
cd backend
python -m pytest tests/integration/test_ldap_api.py tests/test_job_queue_service.py -q
```
