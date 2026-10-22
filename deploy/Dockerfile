# RunPod GPU image for the narrated pipeline: ComfyUI + FLUX.1-schnell fp8,
# Kokoro TTS, WhisperX, and FFmpeg. Build for CUDA 12.1.
#
#   docker build -f deploy/Dockerfile -t narration-pod .
#
# The pod runs two services (expose both ports in the RunPod template):
#   8188 -> ComfyUI       (COMFY_BASE_URL=http://127.0.0.1:8188)
#   8000 -> batch server  (POD_BATCH_PORT=8000, bound to 0.0.0.0)
FROM nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/workspace/hf-cache \
    WORKSPACE=/workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3-pip python3.10-venv git git-lfs ffmpeg curl espeak-ng \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python

WORKDIR /workspace

# CUDA-enabled PyTorch (matches the CUDA 12.1 base image).
RUN pip install --upgrade pip && \
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# ComfyUI
RUN git clone https://github.com/comfyanonymous/ComfyUI /workspace/ComfyUI && \
    pip install -r /workspace/ComfyUI/requirements.txt

# FLUX.1-schnell fp8 all-in-one checkpoint (Apache-2.0; public, no HF login).
RUN mkdir -p /workspace/ComfyUI/models/checkpoints && \
    curl -L -o /workspace/ComfyUI/models/checkpoints/flux1-schnell-fp8.safetensors \
      https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors

# Project + pod extras. The narration-studio extras install Diffusers,
# Transformers, Accelerate and Piper so the default SDXL + IP-Adapter backend
# works without a second ComfyUI-specific image.
COPY . /workspace/long-form-video-generator
WORKDIR /workspace/long-form-video-generator
RUN pip install -r requirements.txt -r deploy/requirements-pod.txt \
    -r deploy/requirements-narration-studio.txt

# Start ComfyUI in the background and the batch server in the foreground.
COPY deploy/entrypoint.sh /workspace/entrypoint.sh
RUN chmod +x /workspace/entrypoint.sh

EXPOSE 8188 8000
ENTRYPOINT ["/workspace/entrypoint.sh"]
