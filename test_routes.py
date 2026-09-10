#!/usr/bin/env python
"""
Test Flask routes and Treblo API connection
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.api.web_app import app

# Print all registered routes
print("=" * 80)
print("REGISTERED FLASK ROUTES")
print("=" * 80)
print()

for rule in app.url_map.iter_rules():
    print(f"{rule.endpoint:30} {rule.rule:50} {rule.methods}")

print()
print("=" * 80)

# Check if music routes are registered
music_routes = [rule for rule in app.url_map.iter_rules() if 'music' in rule.rule]
print(f"Music routes found: {len(music_routes)}")
for route in music_routes:
    print(f"  ✓ {route.rule}")
