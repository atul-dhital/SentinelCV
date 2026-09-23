#!/usr/bin/env python
"""Simple runtime benchmark tool for SentinelCV HTTP endpoints."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests


@dataclass
class EndpointBenchmark:
    name: str
    url: str
    method: str
    samples_ms: List[float]
    success_count: int
    failure_count: int
    last_status_code: Optional[int]

    def summary(self) -> Dict[str, object]:
        if self.samples_ms:
            sorted_samples = sorted(self.samples_ms)
            p95_index = max(0, min(len(sorted_samples) - 1, int(round(len(sorted_samples) * 0.95)) - 1))
            return {
                "name": self.name,
                "url": self.url,
                "method": self.method,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "last_status_code": self.last_status_code,
                "avg_ms": round(statistics.mean(self.samples_ms), 2),
                "min_ms": round(min(self.samples_ms), 2),
                "max_ms": round(max(self.samples_ms), 2),
                "p95_ms": round(sorted_samples[p95_index], 2),
            }
        return {
            "name": self.name,
            "url": self.url,
            "method": self.method,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_status_code": self.last_status_code,
            "avg_ms": None,
            "min_ms": None,
            "max_ms": None,
            "p95_ms": None,
        }


def benchmark_endpoint(
    session: requests.Session,
    *,
    name: str,
    method: str,
    url: str,
    iterations: int,
    timeout: float,
    headers: Optional[Dict[str, str]] = None,
) -> EndpointBenchmark:
    samples: List[float] = []
    success_count = 0
    failure_count = 0
    last_status_code: Optional[int] = None

    for _ in range(iterations):
        start = time.perf_counter()
        try:
            response = session.request(
                method=method,
                url=url,
                timeout=timeout,
                headers=headers,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            last_status_code = response.status_code
            if 200 <= response.status_code < 400:
                samples.append(elapsed_ms)
                success_count += 1
            else:
                failure_count += 1
        except requests.RequestException:
            failure_count += 1

    return EndpointBenchmark(
        name=name,
        url=url,
        method=method,
        samples_ms=samples,
        success_count=success_count,
        failure_count=failure_count,
        last_status_code=last_status_code,
    )


def login(session: requests.Session, api_base_url: str, email: str, password: str, timeout: float) -> Optional[str]:
    response = session.post(
        f"{api_base_url}/auth/login",
        json={"email": email, "password": password},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("access_token")


def print_table(results: List[EndpointBenchmark]) -> None:
    print("=" * 96)
    print("SentinelCV Benchmark Summary")
    print("=" * 96)
    print(f"{'Endpoint':<28} {'Success':>7} {'Fail':>5} {'Avg ms':>10} {'P95 ms':>10} {'Max ms':>10} {'Status':>8}")
    print("-" * 96)
    for result in results:
        summary = result.summary()
        avg_ms = "-" if summary["avg_ms"] is None else f"{summary['avg_ms']:.2f}"
        p95_ms = "-" if summary["p95_ms"] is None else f"{summary['p95_ms']:.2f}"
        max_ms = "-" if summary["max_ms"] is None else f"{summary['max_ms']:.2f}"
        print(
            f"{result.name:<28} "
            f"{summary['success_count']:>7} "
            f"{summary['failure_count']:>5} "
            f"{avg_ms:>10} "
            f"{p95_ms:>10} "
            f"{max_ms:>10} "
            f"{str(summary['last_status_code'] or '-'):>8}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark SentinelCV HTTP endpoints.")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:3001")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--ai-url", default="http://127.0.0.1:8001")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--output", help="Optional JSON output file")
    args = parser.parse_args()

    session = requests.Session()
    results: List[EndpointBenchmark] = []

    public_targets = [
        ("frontend_root", "GET", f"{args.frontend_url}/"),
        ("backend_health", "GET", f"{args.backend_url}/health"),
        ("backend_api_health", "GET", f"{args.api_base_url}/health"),
        ("backend_docs", "GET", f"{args.backend_url}/docs"),
        ("ai_health", "GET", f"{args.ai_url}/health"),
    ]

    for name, method, url in public_targets:
        results.append(
            benchmark_endpoint(
                session,
                name=name,
                method=method,
                url=url,
                iterations=args.iterations,
                timeout=args.timeout,
            )
        )

    token = None
    if args.email and args.password:
        try:
            token = login(session, args.api_base_url, args.email, args.password, args.timeout)
        except requests.RequestException as exc:
            print(f"Authenticated benchmark login failed: {exc}")

    if token:
        headers = {"Authorization": f"Bearer {token}"}
        authenticated_targets = [
            ("auth_me", "GET", f"{args.api_base_url}/auth/me"),
            ("dashboard_stats", "GET", f"{args.api_base_url}/logs/stats/dashboard"),
            ("system_health", "GET", f"{args.api_base_url}/analytics/system-health"),
            ("notifications", "GET", f"{args.api_base_url}/notifications/unread-count"),
        ]
        for name, method, url in authenticated_targets:
            results.append(
                benchmark_endpoint(
                    session,
                    name=name,
                    method=method,
                    url=url,
                    iterations=args.iterations,
                    timeout=args.timeout,
                    headers=headers,
                )
            )

    print_table(results)

    if args.output:
        output_path = Path(args.output)
        payload = [result.summary() for result in results]
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote benchmark output to {output_path}")

    return 1 if any(result.failure_count for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
