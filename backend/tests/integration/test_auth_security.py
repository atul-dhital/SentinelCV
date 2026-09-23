API = "/api/v1/auth"


def test_login_rate_limit_returns_429(client, admin_user, monkeypatch):
    class _FakeRedisService:
        def check_rate_limit(self, key, max_requests, window_seconds):
            return {
                "allowed": False,
                "current": max_requests,
                "limit": max_requests,
                "remaining": 0,
                "retry_after": 120,
            }

    monkeypatch.setattr("api.auth.get_redis_service", lambda: _FakeRedisService(), raising=False)

    response = client.post(
        f"{API}/login",
        json={"email": "admin@test.com", "password": "Admin123!"},
    )

    assert response.status_code == 429, response.text
    assert response.json()["detail"] == "Rate limit exceeded for login_ip"
    assert response.headers["Retry-After"] == "120"
    assert response.headers["X-RateLimit-Remaining"] == "0"


def test_security_headers_and_pgvector_readiness_are_exposed(client):
    response = client.get("/health/readiness")

    assert response.status_code == 200, response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == "camera=(self), microphone=(self), geolocation=()"

    payload = response.json()
    assert "pgvector_face_index" in payload["checks"]
    assert payload["checks"]["pgvector_face_index"]["value"] == "not_applicable"
    assert payload["checks"]["embedding_key_separation"]["status"] == "pass"
    assert payload["checks"]["embedding_key_separation"]["value"] == "dedicated"


def test_readiness_exposes_pgvector_pass_status_when_backend_ready(client, monkeypatch):
    monkeypatch.setattr("main._database_backend", lambda: "postgresql")
    monkeypatch.setattr("main._pgvector_extension_check", lambda: {
        "status": "pass",
        "value": "installed",
        "detail": "pgvector extension is available.",
    })
    monkeypatch.setattr("main._pgvector_face_index_check", lambda: {
        "status": "pass",
        "value": "hnsw",
        "detail": "Verified hnsw ANN index on face_data embeddings.",
        "indexes": [{"name": "ix_face_data_embedding_hnsw"}],
    })

    response = client.get("/health/readiness")
    assert response.status_code == 200, response.text

    payload = response.json()
    checks = payload["checks"]

    assert checks["database_backend"]["value"] == "postgresql"
    assert checks["database_backend"]["status"] == "pass"
    assert checks["pgvector_extension"]["status"] == "pass"
    assert checks["pgvector_face_index"]["status"] == "pass"
    assert checks["pgvector_face_index"]["value"] == "hnsw"


def test_readiness_warns_when_embedding_key_matches_secret_key(client, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "shared-secret-key-that-is-definitely-long-enough")
    monkeypatch.setenv("EMBEDDING_KEY_SECRET", "shared-secret-key-that-is-definitely-long-enough")

    response = client.get("/health/readiness")
    assert response.status_code == 200, response.text

    checks = response.json()["checks"]
    assert checks["embedding_key_separation"]["status"] == "warn"
    assert checks["embedding_key_separation"]["value"] == "shared_or_missing"
