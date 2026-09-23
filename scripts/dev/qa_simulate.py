import requests
import json
import os
import sys
import uuid
import base64

BASE_URL = "http://localhost:8000/api/v1"
IMAGE_PATH = r"C:\Users\dhita\.gemini\antigravity-ide\brain\db5e3c0b-96ef-4b3f-8843-cec0c97ba600\dummy_face_1780197694455.png"

def print_step(msg):
    print(f"\n[+] {msg}")

def run_qa():
    print("Starting Automated QA for Face Assignment & Live Recognition...")
    unique_id = str(uuid.uuid4())[:8]
    email = f"qa_{unique_id}@democustomer.com"
    
    # 1. Register Auth User to get Token
    print_step(f"1. Registering QA organization (Email: {email})...")
    resp = requests.post(f"{BASE_URL}/auth/register", json={
        "organization_name": f"QA Org {unique_id}",
        "email": email,
        "full_name": "QA Admin",
        "password": "Password123!"
    })
    resp.raise_for_status()
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Successfully authenticated and acquired JWT token.")
    
    # 2. Register a Visitor
    print_step("2. Registering a visitor profile...")
    v_resp = requests.post(f"{BASE_URL}/visitors/", json={
        "full_name": f"User {unique_id}",
        "visitor_type": "employee"
    }, headers=headers)
    v_resp.raise_for_status()
    visitor_id = v_resp.json()["id"]
    visitor_name = v_resp.json()["name"]
    print(f"Visitor registered successfully! ID: {visitor_id}")
    
    # 3. Assign Face to Visitor
    print_step("3. Assigning face to visitor (Simulating webcam capture)...")
    with open(IMAGE_PATH, "rb") as f:
        f_resp = requests.post(
            f"{BASE_URL}/visitors/{visitor_id}/face-upload",
            files={"file": ("face.png", f, "image/png")},
            headers=headers
        )
    f_resp.raise_for_status()
    print("Face assigned to profile successfully! Embedding generated.")
    
    # 4. Start Live Camera Session
    print_step("4. Starting Live Camera Session...")
    s_resp = requests.post(f"{BASE_URL}/camera/start-session", json={}, headers=headers)
    s_resp.raise_for_status()
    session_id = s_resp.json()["id"]
    print(f"Session started: {session_id}")
    
    # 5. Process Frame
    print_step("5. Processing Frame via Live Activities...")
    with open(IMAGE_PATH, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
        
    p_resp = requests.post(f"{BASE_URL}/camera/process-frame", json={
        "session_id": session_id,
        "frame_data": img_b64
    }, headers=headers)
    
    if p_resp.status_code == 200:
        results = p_resp.json()
        print(f"Live Activities Response: {json.dumps(results, indent=2)}")
        detections = results.get("detections", [])
        found = False
        for det in detections:
            if det.get("identified") and det.get("visitor_id") == visitor_id:
                print(f"\n=> SUCCESS! The face was successfully recognized as '{visitor_name}' with confidence {det.get('confidence', 0)*100:.2f}%.")
                found = True
                break
        if not found:
            print("\n=> WARNING: The visitor was NOT identified in the frame.")
    else:
        print(f"Frame processing failed: {p_resp.status_code} {p_resp.text}")
        
    # 6. End Session
    print_step("6. Ending Live Camera Session...")
    requests.post(f"{BASE_URL}/camera/end-session/{session_id}", headers=headers)
    print("QA Complete.")

if __name__ == "__main__":
    run_qa()
