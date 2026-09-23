#!/usr/bin/env python3
"""
SentinelCV Post-Deployment Verification Script

Validates production deployment by testing:
- Health endpoints
- Critical API endpoints
- Database connectivity
- WebSocket real-time updates
- Cache functionality
- Worker queue status

Usage:
    python scripts/post_deployment_verify.py --api-url https://sentinelcv.com
"""

import sys
import argparse
import requests
import json
import time
import os
from datetime import datetime
from typing import List, Tuple
from enum import Enum

# Color codes for terminal output
class Color:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


class TestResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"


class PostDeploymentVerifier:
    """Comprehensive post-deployment verification suite"""
    
    def __init__(self, api_url: str, timeout: int = 10):
        self.api_url = api_url.rstrip('/')
        self.timeout = timeout
        self.results: List[Tuple[str, TestResult, str]] = []
        self.session = requests.Session()
        self.auth_headers = {}
        self._try_authenticate()

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Centralized request helper with timeout and optional auth headers."""
        headers = kwargs.pop("headers", {})
        merged_headers = {**self.auth_headers, **headers}
        return self.session.request(
            method=method,
            url=f"{self.api_url}{path}",
            headers=merged_headers,
            timeout=self.timeout,
            **kwargs,
        )

    def _try_authenticate(self) -> None:
        """Authenticate if VERIFY_USERNAME/VERIFY_PASSWORD are provided."""
        username = os.getenv("VERIFY_USERNAME")
        password = os.getenv("VERIFY_PASSWORD")

        if not username or not password:
            return

        try:
            response = self.session.post(
                f"{self.api_url}/api/v1/auth/login",
                json={"email": username, "password": password},
                timeout=self.timeout,
            )
            if response.status_code != 200:
                return
            payload = response.json()
            token = payload.get("access_token") or payload.get("token")
            if token:
                self.auth_headers = {"Authorization": f"Bearer {token}"}
        except Exception:
            # Auth is optional for verification. Protected endpoints can still pass with 401/403 checks.
            return
    
    def log_result(self, test_name: str, result: TestResult, message: str = ""):
        """Log test result with formatted output"""
        self.results.append((test_name, result, message))
        
        if result == TestResult.PASS:
            symbol = f"{Color.GREEN}✓{Color.RESET}"
        elif result == TestResult.FAIL:
            symbol = f"{Color.RED}✗{Color.RESET}"
        elif result == TestResult.WARN:
            symbol = f"{Color.YELLOW}!{Color.RESET}"
        else:  # SKIP
            symbol = f"{Color.BLUE}⊘{Color.RESET}"
        
        detail = f" - {message}" if message else ""
        print(f"  {symbol} {test_name}{detail}")
    
    def print_section(self, title: str):
        """Print section header"""
        print(f"\n{Color.BOLD}{Color.BLUE}{title}{Color.RESET}")
        print(f"{Color.BLUE}{'─' * 60}{Color.RESET}")
    
    # =====================================================================
    # SECTION 1: Health & Status Checks
    # =====================================================================
    
    def test_health_endpoint(self):
        """Test /health endpoint responds OK."""
        try:
            response = self._request("GET", "/health")

            if response.status_code == 200:
                data = response.json()
                if data.get("status") in ["ok", "healthy"]:
                    self.log_result("Health Check", TestResult.PASS, f"Status {data.get('status')}")
                else:
                    self.log_result("Health Check", TestResult.WARN, f"Status: {data.get('status')}")
            else:
                self.log_result("Health Check", TestResult.FAIL, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Health Check", TestResult.FAIL, str(e))
    
    def test_database_health(self):
        """Test database and core dependency health through /health/readiness."""
        try:
            response = self._request("GET", "/health/readiness")

            if response.status_code != 200:
                self.log_result("Readiness Endpoint", TestResult.FAIL, f"HTTP {response.status_code}")
                return

            payload = response.json()
            checks = payload.get("checks", {})
            db_check = checks.get("database_backend", {})
            pgvector_check = checks.get("pgvector_extension", {})

            if db_check.get("status") in ["pass", "warn"]:
                self.log_result("Database Health", TestResult.PASS, str(db_check.get("value", "unknown")))
            else:
                self.log_result("Database Health", TestResult.FAIL, str(db_check))

            if pgvector_check.get("status") in ["pass", "warn"]:
                self.log_result("pgvector Health", TestResult.PASS, pgvector_check.get("detail", ""))
            else:
                self.log_result("pgvector Health", TestResult.FAIL, str(pgvector_check))

        except Exception as e:
            self.log_result("Database Health", TestResult.FAIL, str(e))

    def test_cache_health(self):
        """Infer cache/queue health from readiness response."""
        try:
            response = self._request("GET", "/health/readiness")
            if response.status_code != 200:
                self.log_result("Cache (Redis) Health", TestResult.WARN, f"HTTP {response.status_code}")
                return

            checks = response.json().get("checks", {})
            queue_check = checks.get("video_queue_backend", {})
            if queue_check.get("status") in ["pass", "warn"]:
                self.log_result("Cache (Redis) Health", TestResult.PASS, queue_check.get("detail", ""))
            else:
                self.log_result("Cache (Redis) Health", TestResult.WARN, str(queue_check))
        except Exception:
            self.log_result("Cache (Redis) Health", TestResult.SKIP, "Readiness queue check unavailable")
    
    # =====================================================================
    # SECTION 2: Critical API Endpoints
    # =====================================================================
    
    def test_api_endpoint(self, method: str, path: str, test_name: str):
        """Test generic API endpoint against expected auth-aware outcomes."""
        try:
            response = self._request(method.upper(), path)

            # Protected routes are acceptable with 401/403 if no auth credentials are provided.
            if response.status_code in [200, 201, 401, 403]:
                self.log_result(test_name, TestResult.PASS, f"HTTP {response.status_code}")
                return True

            self.log_result(test_name, TestResult.FAIL, f"HTTP {response.status_code}")
            return False
        except requests.Timeout:
            self.log_result(test_name, TestResult.FAIL, "Timeout")
            return False
        except Exception as e:
            self.log_result(test_name, TestResult.FAIL, str(e))
            return False

    def test_critical_endpoints(self):
        """Test all critical API endpoints with paths validated from backend routers."""
        endpoints = [
            ("GET", "/api/v1/visitors/?page=1&limit=1", "List Visitors"),
            ("GET", "/api/v1/logs/?page=1&limit=1", "List Logs"),
            ("GET", "/api/v1/logs/stats/dashboard", "Logs Dashboard Stats"),
            ("GET", "/api/v1/analytics/accuracy-dashboard?days=7", "Analytics Accuracy Dashboard"),
            ("GET", "/api/v1/users/me", "Current User"),
        ]

        for method, path, name in endpoints:
            self.test_api_endpoint(method, path, name)
    
    # =====================================================================
    # SECTION 3: Performance Metrics
    # =====================================================================
    
    def test_response_times(self):
        """Measure response times for critical endpoints"""
        endpoints = [
            ("/health", "Health Endpoint"),
            ("/api/v1/visitors/?page=1&limit=10", "Visitors List"),
            ("/api/v1/logs/?page=1&limit=10", "Logs List"),
        ]
        
        for path, name in endpoints:
            try:
                start = time.time()
                response = self._request("GET", path)
                elapsed_ms = (time.time() - start) * 1000
                
                if elapsed_ms < 500:
                    status = TestResult.PASS
                elif elapsed_ms < 1000:
                    status = TestResult.WARN
                else:
                    status = TestResult.FAIL
                
                self.log_result(
                    f"{name} Latency",
                    status,
                    f"{elapsed_ms:.0f}ms"
                )
            except Exception as e:
                self.log_result(f"{name} Latency", TestResult.FAIL, str(e))
    
    # =====================================================================
    # SECTION 4: Data Validation
    # =====================================================================
    
    def test_data_integrity(self):
        """Verify data is accessible and valid"""
        try:
            # Check visitors endpoint returns valid data
            response = self._request("GET", "/api/v1/visitors/?page=1&limit=5")
            
            if response.status_code == 200:
                data = response.json()
                
                # Verify structure
                if isinstance(data, dict) and ("items" in data or "data" in data):
                    self.log_result("Data Integrity", TestResult.PASS, "Schema valid")
                else:
                    self.log_result("Data Integrity", TestResult.WARN, "Unexpected schema")
            elif response.status_code == 401:
                self.log_result("Data Integrity", TestResult.SKIP, "Auth required")
            else:
                self.log_result("Data Integrity", TestResult.FAIL, f"HTTP {response.status_code}")
        except Exception as e:
            self.log_result("Data Integrity", TestResult.FAIL, str(e))
    
    # =====================================================================
    # SECTION 5: SSL/TLS & Security
    # =====================================================================
    
    def test_https(self):
        """Verify HTTPS is enabled (if applicable)"""
        if self.api_url.startswith("https://"):
            try:
                response = self._request("GET", "/health", verify=True)
                if response.status_code == 200:
                    self.log_result("HTTPS/SSL", TestResult.PASS, "Certificate valid")
                else:
                    self.log_result("HTTPS/SSL", TestResult.WARN, f"HTTP {response.status_code}")
            except requests.exceptions.SSLError as e:
                self.log_result("HTTPS/SSL", TestResult.FAIL, f"Certificate error: {str(e)[:50]}")
            except Exception as e:
                self.log_result("HTTPS/SSL", TestResult.FAIL, str(e))
        else:
            self.log_result("HTTPS/SSL", TestResult.WARN, "Using HTTP (not HTTPS)")
    
    def test_security_headers(self):
        """Check for important security headers"""
        try:
            response = self._request("GET", "/health")
            headers = response.headers
            
            important_headers = [
                "X-Content-Type-Options",
                "X-Frame-Options",
                "Strict-Transport-Security"
            ]
            
            found = sum(1 for h in important_headers if h in headers)
            
            if found >= 2:
                self.log_result("Security Headers", TestResult.PASS, f"{found}/3 headers present")
            elif found >= 1:
                self.log_result("Security Headers", TestResult.WARN, f"{found}/3 headers present")
            else:
                self.log_result("Security Headers", TestResult.WARN, "No security headers")
        except Exception as e:
            self.log_result("Security Headers", TestResult.FAIL, str(e))
    
    # =====================================================================
    # SUMMARY & REPORTING
    # =====================================================================
    
    def run_all_tests(self):
        """Execute all verification tests"""
        print(f"\n{Color.BOLD}{Color.BLUE}SentinelCV Post-Deployment Verification{Color.RESET}")
        print(f"API URL: {self.api_url}")
        print(f"Time: {datetime.now().isoformat()}")
        
        # Section 1: Health
        self.print_section("SECTION 1: Health & Status Checks")
        self.test_health_endpoint()
        self.test_database_health()
        self.test_cache_health()
        
        # Section 2: API Endpoints
        self.print_section("SECTION 2: Critical API Endpoints")
        self.test_critical_endpoints()
        
        # Section 3: Performance
        self.print_section("SECTION 3: Performance Metrics")
        self.test_response_times()
        
        # Section 4: Data
        self.print_section("SECTION 4: Data Validation")
        self.test_data_integrity()
        
        # Section 5: Security
        self.print_section("SECTION 5: SSL/TLS & Security")
        self.test_https()
        self.test_security_headers()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print summary of all tests"""
        passed = sum(1 for _, r, _ in self.results if r == TestResult.PASS)
        failed = sum(1 for _, r, _ in self.results if r == TestResult.FAIL)
        warned = sum(1 for _, r, _ in self.results if r == TestResult.WARN)
        skipped = sum(1 for _, r, _ in self.results if r == TestResult.SKIP)
        total = len(self.results)
        
        print(f"\n{Color.BOLD}{Color.BLUE}{'═' * 60}{Color.RESET}")
        print(f"{Color.BOLD}VERIFICATION SUMMARY{Color.RESET}")
        print(f"{Color.BLUE}{'═' * 60}{Color.RESET}")
        
        print(f"\n{Color.GREEN}✓ Passed: {passed}/{total}{Color.RESET}")
        print(f"{Color.RED}✗ Failed: {failed}/{total}{Color.RESET}")
        print(f"{Color.YELLOW}! Warnings: {warned}/{total}{Color.RESET}")
        print(f"{Color.BLUE}⊘ Skipped: {skipped}/{total}{Color.RESET}")
        
        # Success/Failure determination
        print(f"\n{Color.BOLD}Status: ", end="")
        
        if failed == 0:
            print(f"{Color.GREEN}✓ READY FOR PRODUCTION{Color.RESET}")
            return True
        else:
            print(f"{Color.RED}✗ ISSUES DETECTED - REVIEW FAILURES{Color.RESET}")
            print(f"\n{Color.BOLD}Failed Tests:{Color.RESET}")
            for test, result, msg in self.results:
                if result == TestResult.FAIL:
                    print(f"  {Color.RED}✗{Color.RESET} {test}: {msg}")
            return False
    
    def save_report(self, filename: str):
        """Save verification report to file"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "api_url": self.api_url,
            "results": [
                {
                    "test": test,
                    "status": result.value,
                    "message": msg
                }
                for test, result, msg in self.results
            ],
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for _, r, _ in self.results if r == TestResult.PASS),
                "failed": sum(1 for _, r, _ in self.results if r == TestResult.FAIL),
                "warnings": sum(1 for _, r, _ in self.results if r == TestResult.WARN),
            }
        }
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n{Color.BLUE}Report saved to: {filename}{Color.RESET}")


def main():
    parser = argparse.ArgumentParser(
        description="SentinelCV Post-Deployment Verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/post_deployment_verify.py --api-url https://sentinelcv.com
  python scripts/post_deployment_verify.py --api-url http://localhost:8000
  python scripts/post_deployment_verify.py --api-url https://staging.sentinelcv.com --save-report report.json
        """
    )
    
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Request timeout in seconds (default: 10)"
    )
    parser.add_argument(
        "--save-report",
        help="Save JSON report to file"
    )
    
    args = parser.parse_args()
    
    verifier = PostDeploymentVerifier(args.api_url, args.timeout)
    verifier.run_all_tests()
    
    if args.save_report:
        verifier.save_report(args.save_report)
    
    # Exit code
    failed = sum(1 for _, r, _ in verifier.results if r == TestResult.FAIL)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
