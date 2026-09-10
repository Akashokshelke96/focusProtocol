"""Smoke test for the independent Colab image service.

Run with:
    python test_colab_image_service.py
"""
from pathlib import Path

from colab_image_service import ColabImageService


if __name__ == "__main__":
    result = ColabImageService().generate_image(
        positive_prompt="A cinematic shot of a futuristic neon city, rain reflections, cybernetic aesthetics, 8k masterpiece",
        negative_prompt="blurry, low quality, distortion, text",
        width=1280,
        height=720,
        steps=20,
        seed=-1,
        output_path=Path("jobs") / "colab_generated_image.png",
    )
    print(f"Success! Seed used: {result.get('seed')}")
    print(f"Saved image: {result['output_path']}")
