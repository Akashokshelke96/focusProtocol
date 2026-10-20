# --- Colab: narrated stickman video test (T4) -------------------------------
# Paste this whole cell into Google Colab and run it.
#
# Only requirement: a Gemini API key.
#   - Add it as a Colab Secret named GEMINI_API_KEY, or
#   - leave the variable below blank and paste it when prompted.
#
# It clones the public repo, installs Kokoro + ComfyUI + SD1.5, and renders a
# ~2-minute narrated video with one generated image per scene.
# Colab's Python 3.13 is too new for Kokoro, so a Python 3.12 venv is created
# automatically for the narration/TTS step. ComfyUI still uses the system Python.
# Test profile: 768x432, 16-24 scenes, SD1.5. Production uses FLUX at 1080p.
# ---------------------------------------------------------------------------

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

REPO = "https://github.com/Akashokshelke96/focusProtocol.git"
PROJECT = Path("/content/focusProtocol")
COMFY = Path("/content/ComfyUI")
CKPT = "v1-5-pruned-emaonly-fp16.safetensors"
COMFY_URL = "http://127.0.0.1:8188"

TOPIC = "Why the Roman road network outlasted the empire that built it"
DURATION_MINUTES = 2.0
GEMINI_API_KEY = ""  # optional if set as a Colab Secret / env var


def run(cmd, **kwargs):
    print("$", cmd if isinstance(cmd, str) else " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


# 1) Resolve the Gemini key --------------------------------------------------
if not GEMINI_API_KEY:
    try:
        from google.colab import userdata
        GEMINI_API_KEY = userdata.get("GEMINI_API_KEY") or ""
    except Exception:
        pass
if not GEMINI_API_KEY:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    from getpass import getpass
    GEMINI_API_KEY = getpass("Gemini API key: ")
assert GEMINI_API_KEY.strip(), "A Gemini API key is required."

# 2) System packages ---------------------------------------------------------
run(["apt-get", "-qq", "update"])
run(["apt-get", "-qq", "install", "-y", "ffmpeg", "espeak-ng", "libsndfile1", "git"])

# 3) Clone the public repo (code only; no music/background assets) -----------
if not (PROJECT / ".git").is_dir():
    if PROJECT.exists():
        shutil.rmtree(PROJECT)
    run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", REPO, str(PROJECT)])
    run(["git", "-C", str(PROJECT), "sparse-checkout", "set",
         "app", "workflows"])
else:
    run(["git", "-C", str(PROJECT), "pull", "--ff-only"])

# 4) Narration deps in a Python 3.12 venv (Kokoro requires <3.13) -------------
run([sys.executable, "-m", "pip", "install", "-q", "--upgrade", "pip", "uv"])
UV = shutil.which("uv")
if not UV:
    for candidate in (Path("/usr/local/bin/uv"), Path("/root/.local/bin/uv"),
                      Path(sys.executable).parent / "uv"):
        if candidate.is_file():
            UV = str(candidate)
            break
assert UV, "uv installation failed"
VENV = Path("/content/narration-venv")
VENV_PY = VENV / "bin" / "python"
if not VENV_PY.is_file():
    run([UV, "venv", "--python", "3.12", str(VENV)])
print("Narration Python:", subprocess.check_output([str(VENV_PY), "--version"], text=True).strip())
run([UV, "pip", "install", "--python", str(VENV_PY),
     "--index-url", "https://download.pytorch.org/whl/cpu", "torch"])
run([UV, "pip", "install", "--python", str(VENV_PY),
     "pydantic", "pydantic-settings", "python-dotenv", "requests", "pillow",
     "numpy", "scipy", "httpx", "websocket-client", "tqdm", "psutil",
     "imageio-ffmpeg", "soundfile", "kokoro"])

# 5) ComfyUI + SD1.5 checkpoint ---------------------------------------------
if not (COMFY / "main.py").is_file():
    run(["git", "clone", "--depth", "1", "https://github.com/comfyanonymous/ComfyUI", str(COMFY)])
    run([sys.executable, "-m", "pip", "install", "-q", "-r", str(COMFY / "requirements.txt")])
ckpt_path = COMFY / "models" / "checkpoints" / CKPT
if not ckpt_path.is_file():
    run(["curl", "-L", "--fail", "-o", str(ckpt_path),
         "https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/" + CKPT])
print("Checkpoint:", ckpt_path, round(ckpt_path.stat().st_size / 2**30, 2), "GB")

# 6) Start ComfyUI -----------------------------------------------------------
try:
    urllib.request.urlopen(COMFY_URL + "/system_stats", timeout=2)
except Exception:
    comfy_log = open("/content/comfyui.log", "ab")
    subprocess.Popen([sys.executable, "main.py", "--listen", "127.0.0.1", "--port", "8188"],
                     cwd=str(COMFY), stdout=comfy_log, stderr=subprocess.STDOUT)
for _ in range(150):
    try:
        urllib.request.urlopen(COMFY_URL + "/system_stats", timeout=2)
        print("ComfyUI is ready")
        break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("ComfyUI did not start; see /content/comfyui.log")

# 7) SD1.5 workflow for this test -------------------------------------------
workflow = json.loads((PROJECT / "workflows" / "sd_txt2img_api.json").read_text(encoding="utf-8"))
workflow["1"]["inputs"]["ckpt_name"] = CKPT
(PROJECT / "workflows" / "colab_sd15_api.json").write_text(json.dumps(workflow), encoding="utf-8")

# 8) Test profile ------------------------------------------------------------
env_values = {
    "NARRATION_ENABLED": "true",
    "NARRATION_REMOTE_ENABLED": "true",
    "NARRATION_TTS_BACKEND": "kokoro_local",
    "NARRATION_TTS_VOICE": "af_heart",
    "NARRATION_MIN_SCENES": "16",
    "NARRATION_MAX_SCENES": "24",
    "NARRATION_SCENE_SECONDS": "2.5",
    "NARRATION_TARGET_DURATION_MINUTES": "2",
    "NARRATION_MOTION": "none",
    "NARRATION_EXPORT_ENABLED": "true",
    "VIDEO_WIDTH": "768",
    "VIDEO_HEIGHT": "432",
    "VIDEO_FPS": "15",
    "COMFY_BASE_URL": COMFY_URL,
    "COMFY_WORKFLOW_PATH": "workflows/colab_sd15_api.json",
    "COMFY_STEPS": "20",
    "COMFY_CFG": "7.0",
    "COMFY_SAMPLER": "euler",
    "COMFY_SCHEDULER": "normal",
    "COMFY_NEGATIVE_PROMPT_ENABLED": "true",
    "LLM_PROVIDER": "gemini",
    "GEMINI_MODEL": "gemini-2.5-flash",
    "GEMINI_API_KEY": GEMINI_API_KEY.strip(),
}
(PROJECT / ".env").write_text("\n".join(f"{k}={v}" for k, v in env_values.items()) + "\n", encoding="utf-8")

# 9) Render one job ----------------------------------------------------------
runner = PROJECT / "run_narration_test.py"
runner.write_text(textwrap.dedent(f"""
    import sys
    from app.config.settings import get_settings
    from app.narration.orchestrator import NarrationOrchestrator

    settings = get_settings()
    print("Profile:", settings.video_width, "x", settings.video_height, settings.video_fps, "fps",
          "scenes", settings.narration_min_scenes, "-", settings.narration_max_scenes,
          "workflow", settings.comfy_workflow_path, flush=True)
    ok = NarrationOrchestrator(settings).run(
        {TOPIC!r}, duration_minutes={float(DURATION_MINUTES)!r}, auto_approve=True, count=1)
    print("RESULT", ok, flush=True)
    sys.exit(0 if ok else 1)
"""), encoding="utf-8")
run([str(VENV_PY), str(runner)], cwd=str(PROJECT),
    env={**os.environ, "PYTHONUNBUFFERED": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})

# 10) Output -----------------------------------------------------------------
videos = sorted((PROJECT / "jobs").glob("*/output/rendered.mp4"), key=lambda p: p.stat().st_mtime)
if not videos:
    videos = sorted((PROJECT / "output").rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
if not videos:
    raise SystemExit("No MP4 found; check the log above (ComfyUI log: /content/comfyui.log).")

video = videos[-1]
print("VIDEO:", video, round(video.stat().st_size / 2**20, 1), "MB")
subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                "format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate",
                "-of", "json", str(video)])
shutil.copy(video, "/content/narration_test.mp4")
print("Copied to /content/narration_test.mp4")

try:
    from IPython.display import Video, display
    display(Video(str(video), embed=True, width=640))
except Exception as error:
    print("Open /content/narration_test.mp4 from the Files pane:", error)
