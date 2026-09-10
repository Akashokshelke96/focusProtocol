#!/usr/bin/env python
"""
Suno API Endpoint Discovery
Test different endpoint patterns to find the correct one
"""
import os
import requests
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

api_key = os.getenv("SUNO_API_KEY")
base_url = "https://api.sunoapi.org"

print("=" * 80)
print("SUNO API ENDPOINT DISCOVERY")
print("=" * 80)
print()
print(f"API Key: {api_key[:20]}...")
print(f"Base URL: {base_url}")
print()

# Test payload
payload = {
    "prompt": "Dark blues instrumental",
    "make_instrumental": True,
    "duration": 30,
}

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

# Endpoint patterns to test
endpoints = [
    "/generate",
    "/api/generate",
    "/v1/generate",
    "/suno/generate",
    "/music/generate",
    "/submit/generate",
    "/task/generate",
]

print("Testing endpoints...")
print()

for endpoint_path in endpoints:
    full_url = f"{base_url}{endpoint_path}"
    print(f"Testing: {full_url}")

    try:
        response = requests.post(
            full_url,
            json=payload,
            headers=headers,
            timeout=10,
        )

        print(f"  Status: {response.status_code}")

        if response.status_code < 500:
            try:
                data = response.json()
                print(f"  Response: {json.dumps(data)[:150]}")
            except:
                print(f"  Response (text): {response.text[:150]}")

        print()

    except Exception as e:
        print(f"  Error: {e}")
        print()

print()
print("=" * 80)
print("If you see a successful response (2xx), that's the correct endpoint path.")
print("=" * 80)
