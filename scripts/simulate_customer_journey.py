import requests
import time
import sys
import uuid

BASE_URL = "http://localhost:8000/api/v1"

def print_step(msg):
    print(f"\n[+] {msg}")

def run():
    print_step("Checking if backend is up...")
    try:
        requests.get("http://localhost:8000/health", timeout=2)
    except Exception:
        print("ERROR: Backend is not running on http://localhost:8000")
        print("Please start the services first using scripts\\START_ALL.ps1")
        sys.exit(1)

    # Use a unique email for every run so we can test the registration flow cleanly
    unique_id = str(uuid.uuid4())[:8]
    email = f"admin_{unique_id}@democustomer.com"

    print_step(f"1. Registering new customer organization (Email: {email})...")
    resp = requests.post(f"{BASE_URL}/auth/register", json={
        "organization_name": f"Demo Customer Corp {unique_id}",
        "email": email,
        "full_name": "Demo Admin",
        "password": "Password123!"
    })
    
    resp.raise_for_status()
    tokens = resp.json()
    token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Registration successful! Authentication token acquired.")

    print_step("2. Getting current user details...")
    me_resp = requests.get(f"{BASE_URL}/auth/me", headers=headers)
    me_resp.raise_for_status()
    me_data = me_resp.json()
    print(f"Logged in as: {me_data['full_name']} (Role: {me_data['role']})")
    print(f"Organization ID: {me_data['organization_id']}")

    print_step("3. Registering a new camera (simulating Edge Node deployment)...")
    cam_resp = requests.post(f"{BASE_URL}/cameras/", headers=headers, json={
        "name": "Main Entrance Camera",
        "rtsp_url": "rtsp://8.8.8.8:8554/stream", # Using a public IP format to bypass localhost restrictions
        "location": "Front Lobby"
    })
    
    cam_resp.raise_for_status()
    cam_data = cam_resp.json()
    cam_id = cam_data['id']
    print(f"Camera registered successfully! ID: {cam_id}")

    print_step("4. Registering an expected visitor...")
    visitor_resp = requests.post(f"{BASE_URL}/visitors/", headers=headers, json={
        "full_name": "John Doe",
        "visitor_type": "contractor",
        "expected_arrival": "2026-06-01T09:00:00Z"
    })
    
    visitor_resp.raise_for_status()
    v_data = visitor_resp.json()
    print(f"Visitor registered successfully! ID: {v_data['id']}")

    print_step("5. Checking Camera Health Dashboard...")
    health_resp = requests.get(f"{BASE_URL}/cameras/health", headers=headers)
    health_resp.raise_for_status()
    print("Camera Health Check:")
    for cam in health_resp.json():
        print(f"  - {cam['camera_name']}: Status={cam['status']}, Uptime={cam['uptime_percent']}%")

    print("\n=======================================================")
    print("SUCCESS! Simulated Customer Journey completed flawlessly.")
    print("=======================================================\n")

if __name__ == "__main__":
    run()
