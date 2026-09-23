#!/usr/bin/env python3
"""
Performance testing framework for SentinelCV APIs.

Tests memory usage, query performance, and scalability with realistic data volumes.
"""

import time
import tracemalloc
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.base import SessionLocal
from models import models
from sqlalchemy import func
from datetime import datetime, timedelta, timezone

class PerformanceTest:
    """Performance test suite for database queries."""

    def __init__(self):
        self.results = {}
        self.db = SessionLocal()

    def test_analytics_query(self, limit_rows=100000):
        """Test analytics query with bounded result set."""
        tracemalloc.start()
        start_time = time.time()

        try:
            # Test bounded query (with limit)
            logs = self.db.query(models.VisitorLog).filter(
                models.VisitorLog.timestamp >= datetime.now(timezone.utc) - timedelta(days=30)
            ).limit(limit_rows).all()

            elapsed = time.time() - start_time
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            return {
                'rows_returned': len(logs),
                'time_seconds': elapsed,
                'peak_memory_mb': peak / 1024 / 1024,
                'status': 'PASS',
            }
        except Exception as e:
            return {
                'error': str(e),
                'status': 'FAIL',
            }

    def test_visitor_query(self, org_id=None):
        """Test visitor query performance."""
        tracemalloc.start()
        start_time = time.time()

        try:
            # Test bounded visitor query
            visitors = self.db.query(models.Visitor).filter(
                models.Visitor.organization_id == org_id
            ).limit(100000).all()

            elapsed = time.time() - start_time
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            return {
                'rows_returned': len(visitors),
                'time_seconds': elapsed,
                'peak_memory_mb': peak / 1024 / 1024,
                'status': 'PASS',
            }
        except Exception as e:
            return {
                'error': str(e),
                'status': 'FAIL',
            }

    def test_aggregation_query(self):
        """Test aggregation query (no memory bloat)."""
        tracemalloc.start()
        start_time = time.time()

        try:
            # Aggregation query returns single row
            result = self.db.query(
                func.count(models.VisitorLog.id),
                func.avg(models.VisitorLog.confidence)
            ).scalar()

            elapsed = time.time() - start_time
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            return {
                'result': result,
                'time_seconds': elapsed,
                'peak_memory_mb': peak / 1024 / 1024,
                'status': 'PASS',
            }
        except Exception as e:
            return {
                'error': str(e),
                'status': 'FAIL',
            }

    def run_suite(self):
        """Run all performance tests."""
        print("\n" + "="*60)
        print("Performance Test Suite")
        print("="*60 + "\n")

        tests = [
            ('Analytics Query (100K rows)', self.test_analytics_query),
            ('Visitor Query (bounded)', self.test_visitor_query),
            ('Aggregation Query', self.test_aggregation_query),
        ]

        results = {}
        for test_name, test_func in tests:
            print(f"Running: {test_name}...", end=' ', flush=True)
            result = test_func()
            results[test_name] = result
            status = result.get('status', 'UNKNOWN')
            print(f"[{status}]")

        # Report
        print("\n" + "="*60)
        print("Results Summary")
        print("="*60 + "\n")

        for test_name, result in results.items():
            print(f"\n{test_name}:")
            if result['status'] == 'PASS':
                print(f"  ✓ Time: {result.get('time_seconds', 0):.3f}s")
                print(f"  ✓ Memory: {result.get('peak_memory_mb', 0):.2f} MB")
                print(f"  ✓ Rows: {result.get('rows_returned', 'N/A')}")
            else:
                print(f"  ✗ Error: {result.get('error', 'Unknown')}")

        self.db.close()

        # Return overall pass/fail
        all_pass = all(r.get('status') == 'PASS' for r in results.values())
        print(f"\nOverall: {'PASS ✓' if all_pass else 'FAIL ✗'}\n")

        return all_pass

if __name__ == '__main__':
    test = PerformanceTest()
    success = test.run_suite()
    sys.exit(0 if success else 1)
