# SentinelCV

SentinelCV is a multi-service visitor-tracking system: a Next.js operator dashboard, a FastAPI API, and AI services for person/face processing, liveness, and camera workflows.

## Current runtime shape

- **Frontend:** Next.js 16 / React 19 on `http://localhost:3001`.
- **Backend:** FastAPI on `http://localhost:8000`; OpenAPI at `/docs`.
- **AI service:** local service on `http://localhost:8001`.
- **Data:** SQLite fallback for local development; PostgreSQL + pgvector for production. Redis enables durable queues and distributed rate limiting when configured.
- **Security:** bearer access token in frontend memory; rotated refresh token in an HTTP-only cookie. Tenant filtering is enabled by default.

Primary product routes are visitors, logs, cameras, users, alerts, reports, compliance, and organization administration. Research/Phase 3 routers are disabled unless explicitly enabled with `ENABLE_EXPERIMENTAL_FEATURES=1` or `ENABLE_PHASE3_FEATURES=1`; production startup rejects either flag.

## Disaster response

SentinelCV includes a Disaster Missing-Person Identification and Reunification
workspace. Authorized staff can create disaster events, import missing-person
records from CSV, report located people privately, and review AI-suggested
matches before updating a case. See the
[implementation plan](docs/project-truth/DISASTER_MISSING_PERSON_IMPLEMENTATION_PLAN.md)
for workflow and privacy safeguards.

## Start locally

Copy and review environment settings first:

```powershell
Copy-Item .env.example .env
```

Then start the local stack:

```powershell
.\scripts\START_ALL.ps1
```

Check `http://localhost:8000/health/readiness`, then open `http://localhost:3001`.

For manual startup and troubleshooting, use [the local full-stack guide](docs/operations/LOCAL_FULL_STACK_GUIDE.md). Backend-only instructions are in [backend/README.md](backend/README.md).

## Repository map

```text
backend/       FastAPI routes, services, SQLAlchemy models, Alembic migrations
frontend/      Next.js dashboard and API client
ai_services/   Recognition, liveness, and inference services
scripts/       Local startup and preflight tooling
docs/          Current docs, operations guides, planning, and historical archive
```

## Documentation

Start with [docs/README.md](docs/README.md). Runtime facts belong in [docs/project-truth](docs/project-truth/README.md); historical narratives are in `docs/archive/` and must not be used as implementation truth.

For coding work, read [AGENTS.md](AGENTS.md) first. It defines the canonical route, schema, auth, and frontend-contract files.
