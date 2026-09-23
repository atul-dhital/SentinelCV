"""Smoke tests for API modules that previously had no direct integration coverage.

These tests verify that the documented GET endpoints for six API modules are:
  1. Reachable (no 5xx errors)
  2. Protected (return 401/403 without auth)
  3. Accept valid admin credentials (return 2xx/404/422, never 5xx)

Covered modules:
  - /api/v1/accuracy
  - /api/v1/data-quality
  - /api/v1/edge-devices
  - /api/v1/learning
  - /api/v1/notifications
  - /api/v1/organizations

This is deliberately a shallow "smoke" layer. It catches:
  * Import-time errors (module fails to load)
  * Route-wiring regressions (404 where a route used to exist)
  * Auth regressions (endpoint accidentally made public)
  * Handler crashes on the empty-DB case (unhandled None, KeyError, etc.)

It does NOT cover business logic — that belongs in per-feature test files.
"""

from __future__ import annotations

import pytest


# GET endpoints that take no path parameters and should be callable
# against an empty test database without setup. Each tuple is:
#   (path, human-readable label)
SMOKE_GET_ENDPOINTS: list[tuple[str, str]] = [
    ("/api/v1/accuracy/stats", "accuracy stats"),
    ("/api/v1/accuracy/liveness-config", "accuracy liveness config"),
    ("/api/v1/accuracy/anti-spoofing-config", "accuracy anti-spoofing config"),
    ("/api/v1/data-quality/config", "data-quality config"),
    ("/api/v1/data-quality/report", "data-quality report"),
    ("/api/v1/data-quality/trends", "data-quality trends"),
    ("/api/v1/edge-devices/", "edge-devices list"),
    ("/api/v1/edge-devices/dashboard/summary", "edge-devices dashboard summary"),
    ("/api/v1/learning/stats", "learning stats"),
    ("/api/v1/learning/samples", "learning samples"),
    ("/api/v1/learning/quality", "learning quality"),
    ("/api/v1/notifications/", "notifications list"),
    ("/api/v1/notifications/unread-count", "notifications unread count"),
    ("/api/v1/notifications/preferences", "notifications preferences"),
    ("/api/v1/organizations/me", "organizations me"),
    ("/api/v1/organizations/me/stats", "organizations me stats"),
]


@pytest.mark.parametrize("path,label", SMOKE_GET_ENDPOINTS, ids=[e[1] for e in SMOKE_GET_ENDPOINTS])
def test_endpoint_requires_auth(client, path, label):
    """Every listed endpoint must reject unauthenticated requests."""
    response = client.get(path)
    assert response.status_code in (401, 403), (
        f"{label} ({path}) returned {response.status_code} without auth; "
        f"expected 401 or 403. Body: {response.text[:200]}"
    )


@pytest.mark.parametrize("path,label", SMOKE_GET_ENDPOINTS, ids=[e[1] for e in SMOKE_GET_ENDPOINTS])
def test_endpoint_admin_does_not_500(client, admin_headers, path, label):
    """Every listed endpoint must not 5xx for an authenticated admin.

    2xx is the happy path, 404/422 are acceptable (empty DB, missing optional data),
    but 5xx indicates an unhandled handler error — a real regression.
    """
    response = client.get(path, headers=admin_headers)
    assert response.status_code < 500, (
        f"{label} ({path}) returned {response.status_code} for admin; "
        f"handler crashed. Body: {response.text[:400]}"
    )
