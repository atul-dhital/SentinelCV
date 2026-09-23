#!/usr/bin/env python3
"""
SentinelCV Feature Verification Test
Tests all major functionality to ensure the project is working
"""

import requests
import os
import sys
import uuid

import pytest


def _backend_up() -> bool:
    """True if a live backend is reachable. This is a manual end-to-end smoke
    test that hits real :8000/:8001 servers — not the in-process TestClient — so
    it must skip (not false-pass, not error) when those servers aren't running."""
    if os.getenv("RUN_LIVE_FEATURE_TESTS") != "1":
        return False
    try:
        requests.get("http://127.0.0.1:8000/health", timeout=2)
        return True
    except Exception:
        return False


def test_features():
    """Pytest entry point: skip without live servers, otherwise assert all features pass."""
    if not _backend_up():
        pytest.skip("Live backend not running on :8000 — run START_ALL then this smoke test.")
    results = _run_feature_checks()
    failed = [name for name, ok in results if not ok]
    assert not failed, f"Feature verification failed for: {', '.join(failed)}"


def _run_feature_checks():
    base_url = "http://127.0.0.1:8000/api/v1"
    ai_url = "http://127.0.0.1:8001"
    test_suffix = uuid.uuid4().hex[:10]
    test_email = f"feature-test-{test_suffix}@test.com"
    
    print("=" * 70)
    print("SENTINELCV FEATURE VERIFICATION TEST")
    print("=" * 70)
    
    results = []
    
    # Test 1: Register user
    print("\n[1/10] USER REGISTRATION")
    try:
        resp = requests.post(f"{base_url}/auth/register", json={
            "email": test_email,
            "password": "Password123!",
            "full_name": "Feature Tester",
            "organization_name": f"Feature Test {test_suffix}",
        }, timeout=5)
        
        if resp.status_code == 200:
            print("✓ User registration successful")
            results.append(("Registration", True))
        else:
            print(f"✗ Registration failed: {resp.status_code}")
            results.append(("Registration", False))
    except Exception as e:
        print(f"✗ Registration error: {e}")
        results.append(("Registration", False))
    
    # Test 2: Login
    print("\n[2/10] AUTHENTICATION (LOGIN)")
    headers = {}
    try:
        resp = requests.post(f"{base_url}/auth/login", json={
            "email": test_email,
            "password": "Password123!"
        }, timeout=5)
        
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            headers = {"Authorization": f"Bearer {token}"}
            print("✓ Login successful, token obtained")
            results.append(("Authentication", True))
        else:
            print(f"✗ Login failed: {resp.status_code}")
            results.append(("Authentication", False))
    except Exception as e:
        print(f"✗ Login error: {e}")
        results.append(("Authentication", False))
    
    if not headers:
        print("\n⚠ Skipping authenticated tests - no valid token")
        return results
    
    # Test 3: User Profile
    print("\n[3/10] USER PROFILE")
    try:
        resp = requests.get(f"{base_url}/auth/me", headers=headers, timeout=5)
        if resp.status_code == 200:
            user = resp.json()
            print(f"✓ Profile retrieved: {user.get('full_name')}")
            results.append(("User Profile", True))
        else:
            print(f"✗ Profile failed: {resp.status_code}")
            results.append(("User Profile", False))
    except Exception as e:
        print(f"✗ Profile error: {e}")
        results.append(("User Profile", False))
    
    # Test 4: Liveness Service Health
    print("\n[4/10] LIVENESS DETECTION SERVICE")
    try:
        resp = requests.get(f"{base_url}/liveness/health", headers=headers, timeout=5)
        if resp.status_code == 200:
            status = resp.json().get('status', 'available')
            print(f"✓ Liveness service healthy: {status}")
            results.append(("Liveness Service", True))
        else:
            print(f"✗ Liveness failed: {resp.status_code}")
            results.append(("Liveness Service", False))
    except Exception as e:
        print(f"✗ Liveness error: {e}")
        results.append(("Liveness Service", False))
    
    # Test 5: Liveness Configuration
    print("\n[5/10] LIVENESS CHALLENGE CONFIGURATION")
    try:
        resp = requests.get(f"{base_url}/liveness/config", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            challenges = data.get('available_challenges', [])
            challenge_str = ', '.join(challenges) if challenges else 'default'
            print(f"✓ Challenge types available: {challenge_str}")
            results.append(("Liveness Config", True))
        else:
            print(f"✗ Config failed: {resp.status_code}")
            results.append(("Liveness Config", False))
    except Exception as e:
        print(f"✗ Config error: {e}")
        results.append(("Liveness Config", False))
    
    # Test 6: Camera Session Management
    print("\n[6/10] CAMERA SESSION MANAGEMENT")
    try:
        resp = requests.post(f"{base_url}/camera/start-session",
            json={"settings": {"source": "browser"}},
            headers=headers, timeout=5)
        
        if resp.status_code == 200:
            session_id = resp.json().get('id')
            print(f"✓ Camera session created: {session_id[:16]}...")
            results.append(("Camera Sessions", True))
        else:
            print(f"✗ Camera session failed: {resp.status_code}")
            results.append(("Camera Sessions", False))
    except Exception as e:
        print(f"✗ Camera session error: {e}")
        results.append(("Camera Sessions", False))
    
    # Test 7: Visitor Management
    print("\n[7/10] VISITOR MANAGEMENT SYSTEM")
    try:
        resp = requests.get(f"{base_url}/visitors", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            count = data.get('total') or data.get('count') or 0
            print(f"✓ Visitors endpoint working: {count} visitors registered")
            results.append(("Visitor Management", True))
        else:
            print(f"✗ Visitors failed: {resp.status_code}")
            results.append(("Visitor Management", False))
    except Exception as e:
        print(f"✗ Visitors error: {e}")
        results.append(("Visitor Management", False))
    
    # Test 8: Alert System
    print("\n[8/10] ALERT NOTIFICATION SYSTEM")
    try:
        resp = requests.get(f"{base_url}/alerts/config", headers=headers, timeout=5)
        if resp.status_code == 200:
            print("✓ Alert system operational")
            results.append(("Alert System", True))
        else:
            print(f"✗ Alerts failed: {resp.status_code}")
            results.append(("Alert System", False))
    except Exception as e:
        print(f"✗ Alerts error: {e}")
        results.append(("Alert System", False))
    
    # Test 9: Dashboard Statistics
    print("\n[9/10] DASHBOARD STATISTICS & ANALYTICS")
    try:
        resp = requests.get(f"{base_url}/logs/stats/dashboard", headers=headers, timeout=5)
        if resp.status_code == 200:
            print("✓ Dashboard analytics available")
            results.append(("Dashboard", True))
        else:
            print(f"✗ Dashboard failed: {resp.status_code}")
            results.append(("Dashboard", False))
    except Exception as e:
        print(f"✗ Dashboard error: {e}")
        results.append(("Dashboard", False))
    
    # Test 10: AI Service
    print("\n[10/10] AI FACE DETECTION & EMBEDDING SERVICE")
    try:
        resp = requests.get(f"{ai_url}/health", timeout=5)
        if resp.status_code == 200:
            print("✓ AI Service ready: Face detection & embeddings available")
            results.append(("AI Service", True))
        else:
            print(f"✗ AI Service failed: {resp.status_code}")
            results.append(("AI Service", False))
    except Exception as e:
        print(f"✗ AI Service error: {e}")
        results.append(("AI Service", False))
    
    return results

def print_summary(results):
    print("\n" + "=" * 70)
    print("TEST RESULTS SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for feature, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status:8} | {feature}")
    
    print("=" * 70)
    print(f"TOTAL: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ ALL FEATURES VERIFIED AND WORKING!")
    else:
        print(f"⚠ {total - passed} features need attention")
    
    print("\n" + "=" * 70)
    print("NEXT STEPS - Test in Browser:")
    print("=" * 70)
    print("📱 Dashboard:     http://localhost:3001")
    print("🎥 Liveness:      http://localhost:3001/liveness")
    print("📹 Live Camera:   http://localhost:3001/camera")
    print("📊 API Docs:      http://localhost:8000/docs")
    print("=" * 70)

if __name__ == "__main__":
    try:
        results = _run_feature_checks()
        print_summary(results)
    except KeyboardInterrupt:
        print("\n\n⚠ Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test suite error: {e}")
        sys.exit(1)
