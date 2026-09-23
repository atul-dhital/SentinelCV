import requests

backend_url = "http://localhost:8000/api/v1"
login_url = f"{backend_url}/auth/login"
health_url = f"{backend_url}/analytics/system-health"

credentials = {
    "email": "admin@test.com",
    "password": "Password123!"
}

session = requests.Session()
try:
    # 1. Login
    login_resp = session.post(login_url, json=credentials)
    print(f"Login Status: {login_resp.status_code}")
    token = login_resp.json().get("access_token")
    
    # 2. Check System Health
    headers = {"Authorization": f"Bearer {token}"}
    health_resp = session.get(health_url, headers=headers)
    print(f"Health Status: {health_resp.status_code}")
    print(f"Health Body: {health_resp.text}")
    
except Exception as e:
    print(f"Error: {e}")
