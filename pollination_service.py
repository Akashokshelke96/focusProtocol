import os
import requests
from pathlib import Path
from urllib.parse import quote
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

POLLINATION_API_KEY = os.getenv("POLLINATION_API_KEY")
POLLINATION_BASE_URL = os.getenv("POLLINATION_BASE_URL", "https://gen.pollinations.ai")
BACKGROUND_IMAGES_DIR = Path(__file__).resolve().parent / "backgroundImages"

BACKGROUND_IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def generate_image(
    prompt: str,
    model: str = "flux",
    width: int = 1080,
    height: int = 1920,
    output_path: Optional[Path] = None,
) -> str | None:
    if not POLLINATION_API_KEY:
        raise RuntimeError("POLLINATION_API_KEY not set in environment")

    encoded_prompt = quote(prompt)
    url = f"{POLLINATION_BASE_URL}/image/{encoded_prompt}"

    params = {
        "model": model,
        "width": width,
        "height": height,
        "key": POLLINATION_API_KEY,
    }

    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()

    safe_name = "".join(c for c in prompt[:50] if c.isalnum() or c in (" ", "-", "_")).strip().replace(" ", "_")
    import uuid
    filepath = Path(output_path) if output_path else BACKGROUND_IMAGES_DIR / f"{safe_name}_{uuid.uuid4().hex[:8]}.jpg"
    filepath.parent.mkdir(parents=True, exist_ok=True)

    filepath.write_bytes(response.content)
    return str(filepath.relative_to(Path(__file__).resolve().parent))


def generate_image_with_auth_header(prompt: str, model: str = "flux", width: int = 1080, height: int = 1920) -> str | None:
    if not POLLINATION_API_KEY:
        raise RuntimeError("POLLINATION_API_KEY not set in environment")

    encoded_prompt = quote(prompt)
    url = f"{POLLINATION_BASE_URL}/image/{encoded_prompt}"

    headers = {"Authorization": f"Bearer {POLLINATION_API_KEY}"}
    params = {"model": model, "width": width, "height": height}

    response = requests.get(url, headers=headers, params=params, timeout=120)
    response.raise_for_status()

    safe_name = "".join(c for c in prompt[:50] if c.isalnum() or c in (" ", "-", "_")).strip().replace(" ", "_")
    import uuid
    filename = f"{safe_name}_{uuid.uuid4().hex[:8]}.jpg"
    filepath = BACKGROUND_IMAGES_DIR / filename

    filepath.write_bytes(response.content)
    return str(filepath.relative_to(Path(__file__).resolve().parent))


if __name__ == "__main__":
    test_prompt = "cinematic oil painting of sun and moon lovers meeting during eclipse, romantic, ethereal lighting"
    try:
        result = generate_image(test_prompt)
        print(f"Saved to: {result}")
    except Exception as e:
        print(f"Error: {e}")