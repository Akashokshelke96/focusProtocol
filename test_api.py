#!/usr/bin/env python
"""Test Treblo API - find correct endpoint"""
import os
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).parent / '.env')

api_key = os.getenv("TREBLO_API_KEY")
if not api_key:
    print("[ERROR] TREBLO_API_KEY not found")
    exit(1)

headers = {"Authorization": f"Bearer {api_key}"}

print("Checking Treblo API base URL...")
try:
    response = requests.get("https://api.treblo.com/", headers=headers, timeout=5)
    print(f"Base URL Status: {response.status_code}")
    if response.status_code < 400:
        print(f"Response: {response.text[:500]}")
except Exception as e:
    print(f"Base URL Error: {e}")

print("\nTrying /v1 endpoint...")
try:
    response = requests.get("https://api.treblo.com/v1", headers=headers, timeout=5)
    print(f"/v1 Status: {response.status_code}")
    if response.status_code < 400:
        print(f"Response: {response.text[:500]}")
except Exception as e:
    print(f"/v1 Error: {e}")

print("\nTrying account endpoint...")
try:
    response = requests.get("https://api.treblo.com/v1/account", headers=headers, timeout=5)
    print(f"/v1/account Status: {response.status_code}")
    if response.status_code < 400:
        print(f"Response: {response.text[:500]}")
except Exception as e:
    print(f"/v1/account Error: {e}")

# Try listing available endpoints
print("\nTrying to get API info...")
endpoints_to_try = [
    "https://api.treblo.com/v1/",
    "https://api.treblo.com/v1/api",
    "https://api.treblo.com/v1/docs",
]

for ep in endpoints_to_try:
    try:
        r = requests.get(ep, headers=headers, timeout=5)
        if r.status_code < 400:
            print(f"{ep}: {r.status_code}")
            print(r.text[:300])
    except:
        pass

# Try OPTIONS to see available methods
print("\nTrying OPTIONS on /v1/...")
try:
    response = requests.options("https://api.treblo.com/v1/", headers=headers, timeout=5)
    print(f"OPTIONS Status: {response.status_code}")
    print(f"Allow header: {response.headers.get('Allow', 'N/A')}")
except Exception as e:
    print(f"OPTIONS Error: {e}")
