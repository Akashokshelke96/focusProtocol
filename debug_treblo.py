#!/usr/bin/env python
"""Debug Treblo API endpoints"""
import os
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).parent / '.env')

api_key = os.getenv("TREBLO_API_KEY")
if not api_key:
    print("[ERROR] TREBLO_API_KEY not found in .env")
    exit(1)

print(f"[OK] API Key found: {api_key[:20]}...")
print()

headers = {"Authorization": f"Bearer {api_key}"}

# Test different endpoints
endpoints = [
    "https://api.treblo.com/v1/generate",
    "https://api.treblo.com/v1/music/generate",
    "https://api.treblo.com/v1/compositions/generate",
    "https://api.treblo.com/generate",
    "https://api.treblo.com/music/generate",
]

test_payload = {
    "prompt": "test",
    "duration": 60,
    "title": "test",
    "style": "dark_blues"
}

print("Testing endpoints...")
for endpoint in endpoints:
    try:
        print(f"\n{endpoint}")
        response = requests.post(endpoint, json=test_payload, headers=headers, timeout=5)
        print(f"  Status: {response.status_code}")
        if response.status_code in [200, 201]:
            print(f"  SUCCESS! Response: {response.json()}")
            break
        else:
            print(f"  Response: {response.text[:200]}")
    except Exception as e:
        print(f"  Error: {str(e)[:100]}")
