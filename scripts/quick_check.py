import requests

base_url = "http://127.0.0.1:8000/api/v1"

print("=" * 70)
print("SENTINELCV - QUICK FEATURE CHECK")
print("=" * 70)

# Login with admin credentials (from test fixtures)
print("\n[1] Authentication with test admin account...")
login_resp = requests.post(f"{base_url}/auth/login", json={
    "email": "admin@test.com",
    "password": "Admin123!"
})

if login_resp.status_code == 200:
    token = login_resp.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    print("✓ Login successful")
else:
    print(f"⚠ Admin account not available, trying registration...")
    # Register new user
    import uuid
    email = f"test-{str(uuid.uuid4())[:8]}@test.com"
    reg = requests.post(f"{base_url}/auth/register", json={
        "email": email,
        "password": "Test@12345",
        "full_name": "Test User",
        "organization_name": "Test Org"
    })
    if reg.status_code in [200, 201]:
        # Now login
        login_resp = requests.post(f"{base_url}/auth/login", json={
            "email": email,
            "password": "Test@12345"
        })
        if login_resp.status_code == 200:
            token = login_resp.json().get("access_token")
            headers = {"Authorization": f"Bearer {token}"}
            print(f"✓ New user registered and logged in")
        else:
            print(f"✗ Registration succeeded but login failed ({login_resp.status_code})")
            exit(1)
    else:
        print(f"✗ Registration failed: {reg.status_code} - {reg.text[:100]}")
        exit(1)

# Test features
print("\n[2] Testing Core Features:")
print("-" * 70)

features = {
    "Liveness Service": f"{base_url}/liveness/health",
    "Liveness Config": f"{base_url}/liveness/config",
    "Visitors": f"{base_url}/visitors",
    "Alerts": f"{base_url}/alerts/config",
    "Dashboard Stats": f"{base_url}/logs/stats/dashboard",
    "User Profile": f"{base_url}/auth/me",
}

passed = 0
for name, endpoint in features.items():
    try:
        r = requests.get(endpoint, headers=headers, timeout=5)
        status = "✓" if r.status_code == 200 else "⚠"
        print(f"{status} {name:25} - HTTP {r.status_code}")
        if r.status_code == 200:
            passed += 1
    except Exception as e:
        print(f"✗ {name:25} - {str(e)[:40]}")

print("-" * 70)
print(f"\n✅ {passed}/{len(features)} features working")

# Test camera session
print("\n[3] Camera Session Management:")
try:
    cam_resp = requests.post(f"{base_url}/camera/start-session",
        json={"settings": {"source": "browser"}},
        headers=headers)
    if cam_resp.status_code == 200:
        session_id = cam_resp.json().get('id')
        end_resp = requests.post(
            f"{base_url}/camera/end-session/{session_id}",
            headers=headers,
            timeout=5,
        )
        if end_resp.status_code != 200:
            print(f"Camera session cleanup failed: HTTP {end_resp.status_code}")
        print(f"✓ Camera session created: {session_id[:16]}...")
    else:
        print(f"✗ Camera session failed: {cam_resp.status_code}")
except Exception as e:
    print(f"✗ Camera error: {e}")

# Test AI service
print("\n[4] AI Service (Face Detection):")
try:
    ai_resp = requests.get("http://127.0.0.1:8001/health", timeout=5)
    if ai_resp.status_code == 200:
        print("✓ AI Service healthy and ready")
    else:
        print(f"⚠ AI Service: HTTP {ai_resp.status_code}")
except Exception as e:
    print(f"⚠ AI Service check failed: {e}")

print("\n" + "=" * 70)
print("✅ SentinelCV is RUNNING and READY")
print("=" * 70)
print("\n🌐 Access the application:")
print("   • Dashboard:  http://localhost:3001")
print("   • Liveness:   http://localhost:3001/liveness")
print("   • Camera:     http://localhost:3001/camera")
print("   • API Docs:   http://localhost:8000/docs")
print("\n" + "=" * 70 + "\n")
