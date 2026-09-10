"""
ACE Music Hosted REST API - Reusable Song Generator
Usage:
    python acemusic_generate.py
    python acemusic_generate.py --output my_song.mp3
    python acemusic_generate.py --duration 300 --instrumental --output track.mp3
"""

import argparse
import base64
import sys
from pathlib import Path

import requests

# ─────────────────────────────────────────────
# CONFIG  (edit these or pass via CLI args)
# ─────────────────────────────────────────────
API_KEY  = "271fd1cf7aa14bda9b2227ec4c797cda"
BASE_URL = "https://api.acemusic.ai"
MODEL    = "acemusic/acestep-v1.5-turbo"


# ─────────────────────────────────────────────
# DEFAULT PROMPT & LYRICS
# ─────────────────────────────────────────────
DEFAULT_CAPTION = """\
Dark, sophisticated, hypnotic blues / cinematic blues track for deep work and \
late-night focus. 78 BPM. Slow masculine baritone vocals, sparse and deliberate. \
Slide electric guitar through warm tube amp, deep warm bass, minimal restrained \
drums. Dark minor-blues harmony. Analog warmth, tape saturation, subtle vinyl \
texture, faint rain atmosphere. No EDM, no pop, no flashy solos. \
Controlled momentum. Quiet power.\
"""

DEFAULT_LYRICS = """\
[Intro - Guitar Lick]

[Verse 1]
No one is coming to save you tonight
The clock keeps moving, the room stays quiet
Pick up the work, put down the phone
Everything worth having you build alone

[Instrumental Break]

[Verse 2]
The city is sleeping, the screen is bright
Another hour, another mile, another night
Stay with the work — nobody has to know
Just keep the fire low and let it grow

[Guitar Solo]

[Verse 3]
Finish what you started, don't look back
The only way forward is staying on track
One more hour, one clean line
Tomorrow belongs to the disciplined mind

[Instrumental Break]

[Outro]
Keep going.
Stay with the work.
Just keep moving.
[Final guitar chord and fade out]
"""


# ─────────────────────────────────────────────
# CORE FUNCTION
# ─────────────────────────────────────────────
def generate_song(
    caption: str,
    lyrics: str,
    duration: int,
    instrumental: bool,
    output_path: Path,
    bpm: int | None = None,
    key: str = "",
    vocal_language: str = "en",
    format: str = "mp3",
) -> Path:
    """
    Call the ACE Music REST API and save the returned audio to output_path.
    Returns the resolved output path on success.
    """
    url = f"{BASE_URL}/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "curl/8.4.0",
    }

    user_content = f"<prompt>{caption}</prompt>"
    if not instrumental:
        user_content += f"\n<lyrics>{lyrics}</lyrics>"

    audio_config: dict = {
        "instrumental": instrumental,
        "duration": duration,
        "format": format,
    }
    if bpm:
        audio_config["bpm"] = bpm
    if key:
        audio_config["key"] = key
    if not instrumental:
        audio_config["vocal_language"] = vocal_language

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": user_content}],
        "audio_config": audio_config,
    }

    print(f"  Endpoint : {url}")
    print(f"  Model    : {MODEL}")
    print(f"  Duration : {duration}s")
    print(f"  BPM      : {bpm or 'auto'}")
    print(f"  Key      : {key or 'auto'}")
    print(f"  Vocals   : {'no (instrumental)' if instrumental else vocal_language}")
    print(f"  Format   : {format.upper()}")
    print()
    print("Sending request …")

    response = requests.post(url, headers=headers, json=payload, timeout=900)

    if response.status_code != 200:
        print(f"\nERROR  HTTP {response.status_code}")
        print(response.text)
        response.raise_for_status()

    data = response.json()
    choices = data.get("choices")
    if not choices:
        raise RuntimeError(f"No choices in response:\n{data}")

    message  = choices[0].get("message", {})
    audio    = message.get("audio")

    if not audio:
        raise RuntimeError(f"No audio in response:\n{data}")

    if not isinstance(audio, list) or len(audio) == 0:
        raise RuntimeError(f"Unexpected audio format: {audio!r}")

    audio_url_obj = audio[0].get("audio_url", {})
    data_url      = audio_url_obj.get("url", "")

    if not data_url:
        raise RuntimeError(f"No url in audio_url:\n{audio[0]}")

    # Strip "data:audio/...;base64," prefix if present
    if "," in data_url:
        _, b64 = data_url.split(",", 1)
    else:
        b64 = data_url

    audio_bytes = base64.b64decode(b64)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    return output_path.resolve()


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate a song via the ACE Music hosted REST API."
    )
    p.add_argument("--output",       default="generated_song.mp3",
                   help="Output file path (default: generated_song.mp3)")
    p.add_argument("--duration",     type=int, default=180,
                   help="Duration in seconds, 10–600 (default: 180)")
    p.add_argument("--bpm",          type=int, default=None,
                   help="BPM, 30–300 (default: auto)")
    p.add_argument("--key",          default="",
                   help="Musical key e.g. 'Am', 'C Major' (default: auto)")
    p.add_argument("--vocal-language", default="en",
                   help="Vocal language ISO code, e.g. en, zh, ja (default: en)")
    p.add_argument("--instrumental", action="store_true",
                   help="Generate instrumental (no vocals)")
    p.add_argument("--format",       default="mp3",
                   choices=["mp3", "flac", "wav", "opus", "aac"],
                   help="Audio format (default: mp3)")
    p.add_argument("--caption",      default=DEFAULT_CAPTION,
                   help="Music description / caption (default: dark blues prompt)")
    p.add_argument("--lyrics",       default=DEFAULT_LYRICS,
                   help="Lyrics text (ignored when --instrumental is set)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    output_path = Path(args.output)

    print()
    print("=" * 60)
    print("  ACE MUSIC  —  Song Generator")
    print("=" * 60)
    print()

    try:
        saved = generate_song(
            caption=args.caption,
            lyrics=args.lyrics,
            duration=args.duration,
            instrumental=args.instrumental,
            output_path=output_path,
            bpm=args.bpm,
            key=args.key,
            vocal_language=args.vocal_language,
            format=args.format,
        )
    except Exception as e:
        print(f"\nFAILED: {e}")
        return 1

    size_mb = saved.stat().st_size / (1024 * 1024)

    print()
    print("=" * 60)
    print("  SONG GENERATED SUCCESSFULLY")
    print("=" * 60)
    print(f"  Saved : {saved}")
    print(f"  Size  : {size_mb:.2f} MB")
    print("=" * 60)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
