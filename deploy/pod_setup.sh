#!/usr/bin/env bash
# One-shot setup for a RunPod GPU pod that runs the narrated pipeline.
#
# Installs ComfyUI + FFmpeg, downloads the FLUX.1-schnell fp8 model set, and
# installs the project + pod Python extras. Idempotent: safe to re-run.
#
# Usage (on the pod):
#   bash deploy/pod_setup.sh
#   python -m app.narration.pod.server   # then expose port 8000 + 8188
set -euo pipefail

WORKSPACE="${WORKSPACE:-/workspace}"
COMFY_DIR="${COMFY_DIR:-$WORKSPACE/ComfyUI}"
PROJECT_DIR="${PROJECT_DIR:-$WORKSPACE/long-form-video-generator}"
MODELS="$COMFY_DIR/models"

echo "==> System packages"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ffmpeg git git-lfs curl
else
  echo "    apt-get not found; ensure ffmpeg/git are installed."
fi

echo "==> ComfyUI"
if [ ! -d "$COMFY_DIR" ]; then
  git clone https://github.com/comfyanonymous/ComfyUI "$COMFY_DIR"
fi
python -m pip install -r "$COMFY_DIR/requirements.txt"

echo "==> FLUX.1-schnell fp8 checkpoint (all-in-one, Apache-2.0; commercial-safe)"
mkdir -p "$MODELS/checkpoints"
[ -f "$MODELS/checkpoints/flux1-schnell-fp8.safetensors" ] || \
  curl -L -o "$MODELS/checkpoints/flux1-schnell-fp8.safetensors" \
    "https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors"

echo "==> Project + pod extras"
cd "$PROJECT_DIR"
python -m pip install -r requirements.txt -r deploy/requirements-pod.txt

echo "==> Environment"
cat <<'EOF'
Set these on the pod (.env):
  COMFY_BASE_URL=http://127.0.0.1:8188
  NARRATION_TTS_BACKEND=kokoro_local
  NARRATION_ALIGN_BACKEND=whisperx_local
  NARRATION_REMOTE_ENABLED=true
  NARRATION_BATCH_WORKSPACE=/workspace/batches
  POD_BATCH_HOST=0.0.0.0
  POD_BATCH_PORT=8000
  POD_BATCH_TOKEN=<shared-secret>
  GEMINI_API_KEY or OPENROUTER_API_KEY

Start services (use a process manager or two terminals):
  python "$COMFY_DIR/main.py" --listen 0.0.0.0 --port 8188 &
  python -m app.narration.pod.server
EOF

echo "==> Done. Expose ports 8188 (ComfyUI) and 8000 (batch server) in the pod template."
