#!/usr/bin/env python
"""
ACE-STEP API DIAGNOSTIC REPORT
Detailed investigation of 504 errors and fetch issues
"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
import requests
import json

load_dotenv(Path(__file__).parent / '.env')
sys.path.insert(0, str(Path(__file__).parent))

from app.config.logging_config import setup_logging, get_logger

logger = None

def test_endpoint(method, url, headers, payload, timeout=30):
    """Test a single endpoint with detailed diagnostics."""
    try:
        logger.info(f"Testing: {method} {url}")
        logger.info(f"  Timeout: {timeout}s")

        if method == 'GET':
            response = requests.get(url, headers=headers, timeout=timeout)
        else:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)

        logger.info(f"  Status: {response.status_code}")
        logger.info(f"  Headers: {dict(response.headers)}")

        try:
            data = response.json()
            logger.info(f"  Response: {json.dumps(data, indent=2)[:500]}")
            return response.status_code, data
        except:
            logger.info(f"  Response (text): {response.text[:300]}")
            return response.status_code, response.text

    except requests.Timeout:
        logger.error(f"  TIMEOUT after {timeout}s")
        return 0, "timeout"
    except Exception as e:
        logger.error(f"  ERROR: {e}")
        return 0, str(e)


def main():
    """Run detailed diagnostics."""
    global logger

    logger = setup_logging()

    logger.info("")
    logger.info("="*80)
    logger.info("ACE-STEP API DIAGNOSTIC REPORT")
    logger.info("="*80)
    logger.info("")

    api_key = os.getenv("ACE_MUSIC_API_KEY")
    base_url = os.getenv("ACE_MUSIC_BASE_URL", "https://api.acemusic.ai")

    logger.info("Configuration:")
    logger.info(f"  API Key: {api_key[:30]}...")
    logger.info(f"  Base URL: {base_url}")
    logger.info("")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "ai_token": api_key,
        "caption": "Dark blues instrumental, 75 BPM, 30 seconds",
        "duration": 30,
        "bpm": 75,
        "batch_size": 1,
        "thinking": True,
        "inference_steps": 32,
        "model": "default",
    }

    # Test 1: Health endpoint
    logger.info("TEST 1: Health Check Endpoint")
    logger.info("-" * 80)
    status, data = test_endpoint("GET", f"{base_url}/health", headers, None, timeout=10)
    logger.info(f"Result: {'PASS' if status == 200 else 'FAIL'}")
    logger.info("")

    # Test 2: Release task endpoint (short timeout)
    logger.info("TEST 2: Release Task Endpoint (10s timeout)")
    logger.info("-" * 80)
    status, data = test_endpoint("POST", f"{base_url}/release_task", headers, payload, timeout=10)
    logger.info(f"Result: {'PASS' if status == 200 else 'FAIL (504 expected here)'}")
    logger.info("")

    # Test 3: Release task endpoint (longer timeout)
    logger.info("TEST 3: Release Task Endpoint (60s timeout - may process)")
    logger.info("-" * 80)
    status, data = test_endpoint("POST", f"{base_url}/release_task", headers, payload, timeout=60)
    if status == 200:
        logger.info("SUCCESS - Task submitted!")
        logger.info(f"Task IDs: {data.get('data', {}).get('task_ids', 'N/A')}")
    logger.info("")

    # Test 4: Alternative endpoint format
    logger.info("TEST 4: Release Task with Alternative Payload")
    logger.info("-" * 80)
    alt_payload = {
        "prompt": "Dark blues instrumental",
        "duration": 30,
        "bpm": 75,
        "num_samples": 1,
    }
    status, data = test_endpoint("POST", f"{base_url}/release_task", headers, alt_payload, timeout=60)
    logger.info("")

    # Analysis
    logger.info("="*80)
    logger.info("DIAGNOSIS")
    logger.info("="*80)
    logger.info("")

    logger.info("ISSUE 1: 504 Gateway Error on /release_task")
    logger.info("-" * 80)
    logger.info("Possible causes:")
    logger.info("  1. ACE-Step backend server is overloaded")
    logger.info("  2. Request payload format is incorrect")
    logger.info("  3. API endpoint URL is wrong")
    logger.info("  4. Network/firewall blocking")
    logger.info("")
    logger.info("Typical 504 solutions:")
    logger.info("  - Wait and retry (most likely - server load)")
    logger.info("  - Check API documentation for exact payload format")
    logger.info("  - Verify API endpoint URL is correct")
    logger.info("  - Try alternative model endpoints")
    logger.info("")

    logger.info("ISSUE 2: JavaScript fetch URL parsing error")
    logger.info("-" * 80)
    logger.info("The error 'Failed to parse URL from /api/test-acemusic' means:")
    logger.info("  - The fetch() call is malformed")
    logger.info("  - The URL is missing the protocol (http:// or https://)")
    logger.info("  - Check the JavaScript is using correct full URL")
    logger.info("")
    logger.info("Fix for web UI:")
    logger.info("  - Ensure fetch URL is: http://localhost:5000/api/test-acemusic")
    logger.info("  - NOT just: /api/test-acemusic (missing hostname)")
    logger.info("")

    logger.info("="*80)
    logger.info("RECOMMENDATIONS")
    logger.info("="*80)
    logger.info("")
    logger.info("1. SHORT TERM: Use local audio generation (fallback)")
    logger.info("   - Generate dark blues audio programmatically")
    logger.info("   - Use episode1_pexels.py which already works")
    logger.info("")
    logger.info("2. MEDIUM TERM: Retry with exponential backoff")
    logger.info("   - ACE-Step may be experiencing temporary load")
    logger.info("   - Implement automatic retry logic")
    logger.info("")
    logger.info("3. LONG TERM: Check ACE-Step status")
    logger.info("   - Visit their status page")
    logger.info("   - Check if /release_task endpoint is documented")
    logger.info("   - Consider alternative music APIs")
    logger.info("")

    logger.info("="*80)
    logger.info("END DIAGNOSTIC REPORT")
    logger.info("="*80)
    logger.info("")

    return 0


if __name__ == "__main__":
    sys.exit(main())
