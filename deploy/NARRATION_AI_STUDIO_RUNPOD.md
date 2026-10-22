# AI-Image Narration Studio on RunPod

This guide runs the same `NarrationStudio` production path used by the dashboard and the Colab notebook: Piper narration, a persistent character bible, canonical reference images, reference-conditioned SDXL scenes through IP-Adapter, FFmpeg assembly, validation, and a separate 1280x720 thumbnail.

It does **not** use the old stickman/2D renderer. Text LLMs author scripts and prompts; they never generate images.

## 1. Recommended pod

| Resource | Minimum | Recommended |
|---|---|---|
| GPU VRAM | 16 GB (T4, L4, A10G) | 24 GB (A10G, L4 24 GB, 4090, A100) |
| Disk | 40 GB free | 80 GB+ network volume |
| CPU | 4 vCPU | 8 vCPU |
| RAM | 16 GB | 32 GB |

The default profile is SDXL base at 1024x576 with model CPU offload. A 16 GB T4 works, but each scene may take roughly 10-25 seconds and a 10-minute video has about 200-240 scenes. A 24 GB GPU is materially faster.

Keep `/workspace` and the Hugging Face cache on a persistent volume. A stop/start without a volume re-downloads several gigabytes and loses finished jobs.

## 2. Install

Use a PyTorch CUDA image. Do not install a second `torch` wheel; the RunPod image already has one.

```bash
cd /workspace
git clone https://github.com/Akashokshelke96/focusProtocol.git
cd focusProtocol

apt-get update
apt-get install -y ffmpeg fonts-dejavu-core

python -m pip install -r requirements.txt
python -m pip install -r deploy/requirements-narration-studio.txt
```

Models downloaded on the first run:

| Model | Approx. size | Source |
|---|---|---|
| SDXL base 1.0 | 6.9 GB | `stabilityai/stable-diffusion-xl-base-1.0` |
| IP-Adapter Plus SDXL | 0.7 GB | `h94/IP-Adapter` |
| Piper `en_US-lessac-medium` | ~63 MB | `rhasspy/piper-voices` |

The first image request loads SDXL. Set `HF_TOKEN` only if Hugging Face requires authentication in your region/account.

## 3. Download the Piper voice

```bash
python - <<'PY'
from pathlib import Path
from huggingface_hub import hf_hub_download

voice_dir = Path("/workspace/piper_voices")
voice_dir.mkdir(parents=True, exist_ok=True)
for name in ("en_US-lessac-medium.onnx", "en_US-lessac-medium.onnx.json"):
    path = hf_hub_download(
        "rhasspy/piper-voices",
        f"en/en_US/lessac/medium/{name}",
        local_dir=str(voice_dir),
    )
    print(path)
PY
```

If the `piper` executable is not on `PATH`, the pipeline falls back to `python -m piper`.

## 4. Configure `.env`

Create `/workspace/focusProtocol/.env`:

```dotenv
# Render profile
VIDEO_WIDTH=1920
VIDEO_HEIGHT=1080
VIDEO_FPS=24
QUALITY_PRESET=1080p
FFMPEG_PRESET=faster
FFMPEG_CRF=23

# Narration timing
NARRATION_TARGET_DURATION_MINUTES=10
NARRATION_SCENE_SECONDS=2.5
NARRATION_MIN_SCENES=1
NARRATION_MAX_SCENES=6000
NARRATION_MANIFEST_BATCH_SIZE=20
NARRATION_MAX_RETRIES=3

# Reference-conditioned image backend
NARRATION_IMAGE_BACKEND=diffusers
NARRATION_IMAGE_MODEL=stabilityai/stable-diffusion-xl-base-1.0
NARRATION_IMAGE_DEVICE=cuda
NARRATION_IMAGE_DTYPE=float16
NARRATION_IMAGE_CPU_OFFLOAD=true
NARRATION_IMAGE_WIDTH=1024
NARRATION_IMAGE_HEIGHT=576
NARRATION_IMAGE_STEPS=28
NARRATION_REFERENCE_WIDTH=832
NARRATION_REFERENCE_HEIGHT=1216
NARRATION_REFERENCE_STEPS=32
NARRATION_IP_ADAPTER_SCALE=0.65
NARRATION_IDENTITY_CHECK_ENABLED=true
NARRATION_MANIFEST_REUSE=true

# Local free TTS + estimated alignment when no WhisperX service is configured
NARRATION_TTS_BACKEND=piper_local
NARRATION_PIPER_MODEL=/workspace/piper_voices/en/en_US/lessac/medium/en_US-lessac-medium.onnx
NARRATION_PIPER_CONFIG=/workspace/piper_voices/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
# 1.0 = natural pace (~170 wpm). Measured: 1.17 -> ~9.3 min for a 1,444-word
# script; verify the probed duration, pauses do not scale linearly.
NARRATION_PIPER_LENGTH_SCALE=1.0
NARRATION_ALIGN_BACKEND=http
NARRATION_ALIGN_URL=

# Optional text LLM. One working key is enough. Omit all keys for the
# deterministic fallback cast/prompts (marked completed_with_fallback).
NARRATION_LLM_PROVIDER=auto
OPENROUTER_API_KEY_NARRATOR=
GEMINI_API_KEY_NARRATOR=

# Optional Hugging Face token
HF_TOKEN=

# Keep artifacts on the volume
NARRATION_EXPORT_ENABLED=false
DATABASE_PATH=/workspace/focusProtocol/jobs/registry.db
```

`NARRATION_IMAGE_CPU_OFFLOAD=true` is the safe default for 16 GB. On a 24 GB card you can set it to `false` for a modest speed gain; if the process runs out of memory, set it back to `true`.

## 5. Verify the backend before rendering

This checks the Python imports, CUDA visibility, and backend configuration without downloading or loading SDXL:

```bash
python - <<'PY'
import json
from app.config.settings import Settings
from app.narration.image_backends import build_image_backend

settings = Settings()
backend = build_image_backend(settings)
try:
    print(json.dumps(backend.health(), indent=2))
finally:
    backend.close()
PY
```

A healthy result includes `"reachable": true`, `"cuda": true`, the GPU name, and the configured model. If `reachable` is false, fix that before starting a long render.

## 6. Real smoke test (same production path)

```bash
cd /workspace/focusProtocol
python -m app.narration.studio \
  --smoke-seconds 30 \
  --topic "What did ancient humans actually do all day?" \
  --job-id smoke_$(date +%Y%m%d_%H%M%S) \
  --json
```

This is not a mocked render. It generates real Piper audio, a real character bible, real reference images, real scene images, an MP4, and a 1280x720 thumbnail. It deliberately forces 1280x720/15 fps and about 3-second scenes to keep the smoke short.

The JSON report includes:

- `checks.all_passed`
- `checks.scene_count` and `checks.scenes_with_images`
- `checks.characters` and `checks.references`
- `output_validation` with width, height, FPS, and stream durations
- `thumbnail_validation` with the 1280x720 size
- `image_generation` and `reference_generation` counters

A fallback status is honest, not a failure: a missing text LLM key produces `source="fallback"` for the cast, and missing WhisperX produces `alignment_source="estimated"`.

## 7. Full video

```bash
cd /workspace/focusProtocol
python -m app.narration.studio \
  --topic "What did ancient humans actually do all day?" \
  --minutes 10
```

To render an approved script instead of letting the text LLM write one, pass a UTF-8 text file. `--topic` still supplies the title and thumbnail headline:

```bash
python -m app.narration.studio \
  --topic "What did ancient humans actually do all day?" \
  --script /workspace/scripts/ancient_humans.txt \
  --minutes 10
```

The script file must contain the narration text only. It is marked approved, so no LLM key is required. The manifest still builds scenes and character ids from the text, and the character bible can still use an LLM if a key is present; otherwise the deterministic fallback cast is used.

Artifacts:

```text
jobs/<job_id>/
  characters/character_bible.json
  characters/<character_id>/reference_full_body_*.png
  characters/<character_id>/reference_portrait_*.png
  manifest/manifest.json
  images/scene_*.png
  audio/narration.wav
  output/rendered.mp4
  output/visual.mp4
  thumbnail/thumbnail.png
  metadata.json
```

The orchestrator validates the MP4 with FFprobe before marking the job complete. It rejects missing scene images, wrong resolution/FPS, mismatched audio/video durations, and a missing or non-1280x720 thumbnail.

## 8. Resume after a disconnect or failure

Resume the same job id; do not create a new one:

```bash
python -m app.narration.studio --resume-job <job_id> --json
```

The pipeline reuses:

- the saved approved script,
- the character bible when its fingerprint still matches,
- valid reference images,
- valid scene images whose prompt/seed/reference/cache key still match,
- the scene manifest when the script and audio duration still match.

To force a full visual regeneration, delete the job's `images/` and `characters/` directories before resuming. To regenerate only one scene, delete that scene's `images/scene_*.png`.

Existing scene images are never silently replaced by unrelated images. If one scene fails every retry, the job stops and reports the missing indexes.

## 9. Batch server (multiple videos)

Start the FastAPI worker on the pod:

```bash
cd /workspace/focusProtocol
export POD_BATCH_HOST=0.0.0.0
export POD_BATCH_PORT=8000
export POD_BATCH_TOKEN=replace-with-a-long-random-token
export NARRATION_BATCH_WORKSPACE=/workspace/batches
python -m app.narration.pod.server
```

Expose port `8000` from the pod. From the local machine, set:

```dotenv
POD_BATCH_URL=https://<POD_ID>-8000.proxy.runpod.net
POD_BATCH_TOKEN=replace-with-a-long-random-token
```

Submit and wait:

```bash
python main.py narration-batch \
  --topics "What did ancient humans actually do all day?, Why do we dream?" \
  --duration 10 \
  --wait \
  --download output/narration
```

The batch engine checkpoints each video at `SCRIPT`, `TTS`, `ALIGN`, `BIBLE`, `MANIFEST`, `IMAGES`, `RENDER`, and `PACKAGE` in `/workspace/batches/<batch_id>/state.json`. Restarting the server and resubmitting the same `--batch-id` skips completed stages.

Check health from a shell:

```bash
curl -s "$POD_BATCH_URL/health" -H "X-Batch-Token: $POD_BATCH_TOKEN" | python -m json.tool
```

The health response reports the image backend, TTS backend, alignment backend, and ComfyUI reachability.

## 10. ComfyUI instead of Diffusers

Diffusers is the default because it supports IP-Adapter reference conditioning in-process. If your pod already runs ComfyUI, set:

```dotenv
NARRATION_IMAGE_BACKEND=comfyui
COMFY_BASE_URL=http://127.0.0.1:8188
COMFY_WORKFLOW_PATH=workflows/sd_txt2img_api.json
```

Be aware: the shipped ComfyUI workflow is **text-only**. The backend logs that reference images were not injected, and identity will be weaker than the Diffusers path. Do not claim reference conditioning for that configuration unless you supply a custom IP-Adapter workflow and wire its inputs.

## 11. Troubleshooting

### `Image backend diffusers is not available: No module named 'torch'`

You installed the requirements into a different Python environment, or replaced the pod's CUDA torch with CPU torch. Activate the same interpreter that runs the pipeline and install a CUDA build of PyTorch for that image.

### CUDA out of memory while loading SDXL

- Keep `NARRATION_IMAGE_CPU_OFFLOAD=true`.
- Reduce `NARRATION_IMAGE_WIDTH/HEIGHT` to 768x432.
- Use a 24 GB GPU.
- Do not run ComfyUI, WhisperX, and Diffusers on the same GPU at once. The orchestrator unloads audio models before the image phase, but an external ComfyUI process is outside its control.

### Piper returns silence or fails

Check that both `NARRATION_PIPER_MODEL` and `NARRATION_PIPER_CONFIG` exist and that the model is the `.onnx` file, not the JSON. Run `python -m piper --help` in the same environment.

### Every scene fails quality checks

Quality checks reject blank/flat/undecodable images. Do not disable them to force a render. Inspect the first failed `images/scene_*_try*.png` and the log flags. Common causes are a broken VAE, a text-only workflow returning a placeholder, or a prompt that the model renders as a solid background.

### Thumbnail validation fails

The final thumbnail must be exactly 1280x720. If the image backend cannot produce a thumbnail source, the pipeline falls back to the first valid scene image and still renders deterministic text. If the file itself is missing, inspect `thumbnail/` and `metadata.json`.

### Text LLM is unavailable

The job still runs with a deterministic fallback cast and prompts and finishes as `completed_with_fallback`. For script-specific casting, set one of `OPENROUTER_API_KEY_NARRATOR` or `GEMINI_API_KEY_NARRATOR`. Free OpenRouter models are rate-limited and can disappear; the client tries the configured fallback models in order. If the shipped defaults return `404` (slug retired) or `429` (shared free tier busy), pick live free slugs from `https://openrouter.ai/models?max_price=0` and set `NARRATION_OPENROUTER_MODEL` plus `NARRATION_LLM_FALLBACK_MODELS`, or route through your own OmniRoute/Gemini key. A `--script` run needs no LLM key at all.

## 12. Honest limitations

- IP-Adapter improves identity consistency but cannot guarantee a perfect face across hundreds of scenes.
- CLIP identity similarity is advisory. It does not understand wardrobe continuity or story logic.
- Fallback prompts are simple narration-derived descriptions, not a substitute for a text LLM.
- A 10-minute video means roughly 200-240 diffusion passes. Budget GPU time accordingly.
- The pipeline validates technical correctness; it does not prove aesthetic quality. Review the smoke contact frames before spending an hour on a full render.
