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
    WORKSPACE=/workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3-pip python3.10-venv git git-lfs ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python

WORKDIR /workspace

# CUDA-enabled PyTorch (matches the CUDA 12.1 base image).
RUN pip install --upgrade pip && \
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# ComfyUI
RUN git clone https://github.com/comfyanonymous/ComfyUI /workspace/ComfyUI && \
    pip install -r /workspace/ComfyUI/requirements.txt

# FLUX.1-schnell fp8 model set (Apache-2.0).
RUN mkdir -p /workspace/ComfyUI/models/{unet,clip,vae} && \
    curl -L -o /workspace/ComfyUI/models/unet/flux1-schnell-fp8.safetensors \
      https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors && \
    curl -L -o /workspace/ComfyUI/models/clip/t5xxl_fp8_e4m3fn.safetensors \
      https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors && \
    curl -L -o /workspace/ComfyUI/models/clip/clip_l.safetensors \
      https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors && \
    curl -L -o /workspace/ComfyUI/models/vae/ae.safetensors \
      https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors

# Project + pod extras
COPY . /workspace/long-form-video-generator
WORKDIR /workspace/long-form-video-generator
RUN pip install -r requirements.txt -r deploy/requirements-pod.txt

# Start ComfyUI in the background and the batch server in the foreground.
COPY deploy/entrypoint.sh /workspace/entrypoint.sh
RUN chmod +x /workspace/entrypoint.sh

EXPOSE 8188 8000
ENTRYPOINT ["/workspace/entrypoint.sh"]
