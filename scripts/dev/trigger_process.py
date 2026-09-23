import requests
import json

url = "http://localhost:8001/process"
data = {
    "organization_id": "6e151285-adf9-4692-95cb-022c0a09393a",
    "video_path": r"d:/college/Final-Year-Documentation/Code/backend/data/raw_videos/c9740dd6-ce21-406b-86f7-109df1081be6.mp4"
}

try:
    response = requests.post(url, json=data, timeout=300)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
