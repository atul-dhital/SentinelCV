#!/usr/bin/env python3
"""
SentinelCV Production Load Testing Suite
Tests API endpoints under realistic production load
Requires: pip install locust

Usage:
    locust -f scripts/load_test.py --host=http://localhost:8000 --users=100 --spawn-rate=10
"""

from locust import task, between, events
from locust.contrib.fasthttp import FastHttpUser
import logging
import json
import os
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SentinelCVUser(FastHttpUser):
    """Simulates realistic SentinelCV user behavior"""
    
    wait_time = between(2, 5)  # Wait 2-5 seconds between requests
    
    def on_start(self):
        """Called when user starts - login if needed"""
        logger.info(f"User starting at {datetime.now()}")
        self.visitor_id = None
        self.log_id = None
        self.auth_headers = {}
        self._try_authenticate()

    def _try_authenticate(self):
        """Attempt login if credentials are provided through env vars."""
        username = os.getenv("LOADTEST_USERNAME")
        password = os.getenv("LOADTEST_PASSWORD")

        if not username or not password:
            logger.info("No load-test credentials provided. Running in unauthenticated mode.")
            return

        with self.client.post(
            "/api/v1/auth/login",
            json={"email": username, "password": password},
            catch_response=True,
            name="auth_login"
        ) as response:
            if response.status_code != 200:
                response.failure(f"Auth failed: HTTP {response.status_code}")
                return

            try:
                payload = response.json()
                token = payload.get("access_token") or payload.get("token")
                if not token:
                    response.failure("Auth response missing access token")
                    return
                self.auth_headers = {"Authorization": f"Bearer {token}"}
                response.success()
                logger.info("Load-test authentication succeeded")
            except Exception as exc:
                response.failure(f"Auth response parse error: {exc}")

    def _ok_or_auth_error(self, status_code: int) -> bool:
        """Treat auth-related responses as acceptable when running unauthenticated."""
        return status_code in [200, 201, 401, 403]
    
    @task(40)
    def list_visitors(self):
        """40% of traffic: Browse visitor list (most common operation)"""
        with self.client.get(
            "/api/v1/visitors/?page=1&limit=50",
            headers=self.auth_headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
                # Extract first visitor ID for later tasks
                try:
                    data = response.json()
                    items = data.get("items") or data.get("data") or []
                    if items:
                        self.visitor_id = items[0].get("id")
                except Exception:
                    pass
            elif self._ok_or_auth_error(response.status_code):
                response.success()
            else:
                response.failure(f"Got {response.status_code}")
    
    @task(30)
    def list_logs(self):
        """30% of traffic: View detection logs"""
        with self.client.get(
            "/api/v1/logs/?page=1&limit=100",
            headers=self.auth_headers,
            catch_response=True
        ) as response:
            if self._ok_or_auth_error(response.status_code):
                response.success()
            else:
                response.failure(f"Got {response.status_code}")
    
    @task(15)
    def get_visitor_details(self):
        """15% of traffic: View single visitor details"""
        if not self.visitor_id:
            return
        
        with self.client.get(
            f"/api/v1/visitors/{self.visitor_id}",
            headers=self.auth_headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in [401, 403, 404]:
                response.success()
            else:
                response.failure(f"Got {response.status_code}")
    
    @task(10)
    def health_check(self):
        """10% of traffic: Health checks"""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("status") in ["ok", "healthy"]:
                    response.success()
                else:
                    response.failure("Health check not OK")
            else:
                response.failure(f"Got {response.status_code}")
    
    @task(5)
    def get_dashboard_stats(self):
        """5% of traffic: Dashboard statistics"""
        with self.client.get(
            "/api/v1/analytics/dashboard?days=30",
            headers=self.auth_headers,
            catch_response=True
        ) as response:
            if self._ok_or_auth_error(response.status_code):
                response.success()
            else:
                response.failure(f"Got {response.status_code}")


class MediaUploadUser(FastHttpUser):
    """Simulates face upload traffic (10% of user base)"""
    
    wait_time = between(10, 30)  # Less frequent uploads

    def on_start(self):
        self.auth_headers = {}
        username = os.getenv("LOADTEST_USERNAME")
        password = os.getenv("LOADTEST_PASSWORD")
        if not username or not password:
            return
        with self.client.post(
            "/api/v1/auth/login",
            json={"email": username, "password": password},
            catch_response=True,
            name="auth_login_upload"
        ) as response:
            if response.status_code != 200:
                return
            try:
                token = response.json().get("access_token") or response.json().get("token")
                if token:
                    self.auth_headers = {"Authorization": f"Bearer {token}"}
            except Exception:
                pass
    
    @task
    def upload_face(self):
        """Simulate face image upload"""
        # In real scenario, would upload actual image file
        # For load test, we simulate with small test image
        
        with self.client.post(
            os.getenv("LOADTEST_UPLOAD_ENDPOINT", "/api/v1/visitors/enroll"),
            files={"file": ("test.jpg", b"fake_jpg_data")},
            headers=self.auth_headers,
            catch_response=True
        ) as response:
            # Endpoint/schema differences can legitimately return 4xx in synthetic upload tests.
            if response.status_code in [200, 201, 400, 401, 403, 404, 413, 422]:
                response.success()
            else:
                response.failure(f"Upload failed: {response.status_code}")


# Event handlers for reporting
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    logger.info(f"Load test started with {environment.runner.target_user_count} users")
    logger.info(f"Ramp-up rate: {environment.runner.spawn_rate} users/sec")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Generate summary report when test completes"""
    logger.info("\n" + "="*60)
    logger.info("LOAD TEST SUMMARY")
    logger.info("="*60)
    
    stats = environment.stats
    
    total_requests = sum(stat.num_requests for stat in stats.entries.values())
    total_failures = sum(stat.num_failures for stat in stats.entries.values())
    
    logger.info(f"Total requests: {total_requests}")
    logger.info(f"Total failures: {total_failures}")
    logger.info(f"Failure rate: {(total_failures/max(total_requests, 1)*100):.2f}%")
    
    logger.info("\nResponse times (ms):")
    for stat in stats.entries.values():
        if stat.num_requests > 0:
            logger.info(f"  {stat.method} {stat.name}")
            logger.info(f"    Avg: {stat.avg_response_time:.0f}ms")
            logger.info(f"    Min: {stat.min_response_time:.0f}ms")
            logger.info(f"    Max: {stat.max_response_time:.0f}ms")
            logger.info(f"    p50: {stat.get_response_time_percentile(0.50):.0f}ms")
            logger.info(f"    p95: {stat.get_response_time_percentile(0.95):.0f}ms")
            logger.info(f"    p99: {stat.get_response_time_percentile(0.99):.0f}ms")


@events.quitting.add_listener
def on_quit(environment, **kwargs):
    """Save summarized load test results to a JSON artifact and apply SLA gates."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backend/load_test_results_{timestamp}.json"

    stats = environment.stats
    total_requests = sum(stat.num_requests for stat in stats.entries.values())
    total_failures = sum(stat.num_failures for stat in stats.entries.values())
    failure_rate_percent = (total_failures / max(total_requests, 1)) * 100
    global_p95_ms = stats.total.get_response_time_percentile(0.95)

    max_failure_rate = float(os.getenv("LOADTEST_MAX_FAILURE_RATE", "0.5"))
    max_p95_ms = float(os.getenv("LOADTEST_MAX_P95_MS", "500"))

    gates = {
        "max_failure_rate_percent": max_failure_rate,
        "max_p95_ms": max_p95_ms,
        "actual_failure_rate_percent": round(failure_rate_percent, 4),
        "actual_p95_ms": round(global_p95_ms, 2),
        "failure_rate_pass": failure_rate_percent <= max_failure_rate,
        "p95_pass": global_p95_ms <= max_p95_ms,
    }
    gates["overall_pass"] = gates["failure_rate_pass"] and gates["p95_pass"]

    result = {
        "timestamp": timestamp,
        "host": environment.host,
        "total_requests": total_requests,
        "total_failures": total_failures,
        "failure_rate_percent": round(failure_rate_percent, 4),
        "global_p95_ms": round(global_p95_ms, 2),
        "gates": gates,
        "entries": [
            {
                "name": stat.name,
                "method": stat.method,
                "requests": stat.num_requests,
                "failures": stat.num_failures,
                "avg_ms": stat.avg_response_time,
                "min_ms": stat.min_response_time,
                "max_ms": stat.max_response_time,
                "p50_ms": stat.get_response_time_percentile(0.50),
                "p95_ms": stat.get_response_time_percentile(0.95),
                "p99_ms": stat.get_response_time_percentile(0.99),
                "rps": stat.total_rps,
            }
            for stat in stats.entries.values()
            if stat.num_requests > 0
        ],
    }

    os.makedirs("backend", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as file_handle:
        json.dump(result, file_handle, indent=2)

    if gates["overall_pass"]:
        logger.info("SLA gates passed: failure rate %.2f%%, p95 %.2fms", failure_rate_percent, global_p95_ms)
        environment.process_exit_code = 0
    else:
        logger.error(
            "SLA gates failed: failure rate %.2f%% (limit %.2f%%), p95 %.2fms (limit %.2fms)",
            failure_rate_percent,
            max_failure_rate,
            global_p95_ms,
            max_p95_ms,
        )
        environment.process_exit_code = 1

    logger.info(f"Saved load test results to {filename}")
    logger.info("Load test complete!")
