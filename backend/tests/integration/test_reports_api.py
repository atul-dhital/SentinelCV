"""Regression tests for report utility endpoints."""

from pathlib import Path


def test_reports_cache_info_returns_metrics(client, admin_headers, monkeypatch):
    class _FakeRedisService:
        def get_metrics(self):
            return {
                "connected": False,
                "using_fallback": True,
                "cache_hits": 3,
                "cache_misses": 1,
                "cache_sets": 2,
                "cache_deletes": 0,
                "cache_errors": 0,
                "fallback_reads": 1,
                "fallback_writes": 1,
                "cache_hit_ratio": 0.75,
                "last_error": None,
                "last_error_at": None,
            }

    monkeypatch.setattr(
        "services.redis_service.get_redis_service",
        lambda: _FakeRedisService(),
        raising=False,
    )

    response = client.get("/api/v1/reports/cache/info", headers=admin_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["using_fallback"] is True
    assert payload["cache_hit_ratio"] == 0.75


def test_reports_quality_summary_exposes_artifacts(client, admin_headers, monkeypatch, tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (tmp_path / "backend" / "tests" / "integration").mkdir(parents=True, exist_ok=True)
    (tmp_path / "backend" / ".pytest_cache" / "v" / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "htmlcov").mkdir(parents=True, exist_ok=True)

    (tmp_path / ".github" / "workflows" / "ci-cd.yml").write_text(
        "pytest backend/tests/unit --cov=backend --cov-report=xml\n",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "README.md").write_text("# Backend\n", encoding="utf-8")
    (tmp_path / "backend" / "tests" / "integration" / "test_sample.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tmp_path / "backend" / "tests" / "test_service.py").write_text("def test_root(): pass\n", encoding="utf-8")
    (tmp_path / "backend" / ".pytest_cache" / "v" / "cache" / "nodeids").write_text(
        '["tests/integration/test_sample.py::test_ok", "tests/test_service.py::test_root"]\n',
        encoding="utf-8",
    )
    (tmp_path / "coverage.xml").write_text("<coverage />\n", encoding="utf-8")
    (tmp_path / "htmlcov" / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (tmp_path / "bandit-report.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr("api.reports._project_root", lambda: Path(tmp_path), raising=False)

    response = client.get("/api/v1/reports/quality/summary", headers=admin_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ci_workflow_present"] is True
    assert payload["coverage_enabled_in_ci"] is True
    assert payload["pytest_collected_tests"] == 2
    assert payload["integration_test_files"] == 1
    assert payload["service_test_files"] == 1
    assert payload["backend_readme_present"] is True
    assert payload["artifacts"]["coverage_xml"]["exists"] is True
    assert payload["artifacts"]["coverage_html"]["exists"] is True
    assert payload["artifacts"]["bandit_report"]["exists"] is True
    assert payload["artifacts"]["pylint_report"]["exists"] is False
