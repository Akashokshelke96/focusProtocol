#!/usr/bin/env bash
# Container entrypoint: run ComfyUI in the background, then the batch server.
set -euo pipefail

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
PYTHON="${PYTHON:-python}"

echo "==> Starting ComfyUI on 0.0.0.0:8188"
"$PYTHON" "$COMFY_DIR/main.py" --listen 0.0.0.0 --port 8188 &

echo "==> Starting narration batch server on 0.0.0.0:${POD_BATCH_PORT:-8000}"
exec "$PYTHON" -m app.narration.pod.server
