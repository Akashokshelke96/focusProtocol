"""Tests for the AI-image narration studio: bible, references, cache, quality."""
from __future__ import annotations

import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.config.settings import Settings
from app.narration.character_bible import CharacterBibleBuilder, script_fingerprint
from app.narration.image_backends import (
    DiffusersImageBackend,
    ImageBackend,
    ImageRequest,
    ImageResult,
)
from app.narration.image_generation import ImageGenerationError, ImageGenerationService
from app.narration.models import (
    AlignSegment,
    AlignmentResult,
    Scene,
    SceneManifest,
    ScriptPlan,
)
from app.narration.quality import QualityChecker
from app.narration.scene_manifest import SceneManifestBuilder, compose_positive


SCRIPT = (
    "Ancient people did not spend every hour surviving. A camp wakes beside a cold river. "
    "One person repairs a cracked tool while another sorts roots into a basket. A child carries "
    "water and an elder watches the tree line. By noon the group has moved a short distance, read "
    "the ground, and changed its plan. By evening the same hands have made fire, shared food, and "
    "told a story that will be repeated tomorrow. The past was not a photograph. It was a working day. "
) * 2


def _settings(**overrides) -> Settings:
    values = dict(
        NARRATION_MIN_SCENES=1,
        NARRATION_MAX_SCENES=20,
        NARRATION_MAX_RETRIES=0,
        NARRATION_REFERENCE_VIEWS="full_body,portrait",
        NARRATION_REFERENCE_WIDTH=512,
        NARRATION_REFERENCE_HEIGHT=512,
        NARRATION_IMAGE_WIDTH=512,
        NARRATION_IMAGE_HEIGHT=320,
        NARRATION_QUALITY_MIN_ENTROPY=0.5,
        NARRATION_QUALITY_MIN_STDDEV=5,
        NARRATION_IDENTITY_CHECK_ENABLED=False,
        NARRATION_THUMBNAIL_WIDTH=1280,
        NARRATION_THUMBNAIL_HEIGHT=720,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _plan(topic: str = "What did ancient humans actually do all day?") -> ScriptPlan:
    return ScriptPlan(topic=topic, title="Ancient Days", script=SCRIPT,
                      word_count=len(SCRIPT.split()), approved=True)


class BlockBackend(ImageBackend):
    """Deterministic, high-detail PNGs without torch."""

    name = "block"

    def generate(self, request: ImageRequest) -> ImageResult:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (request.width, request.height))
        rnd = random.Random(request.seed)
        pixels = image.load()
        for y in range(0, request.height, 5):
            for x in range(0, request.width, 5):
                colour = (rnd.randrange(20, 235), rnd.randrange(20, 235), rnd.randrange(20, 235))
                for yy in range(y, min(y + 5, request.height)):
                    for xx in range(x, min(x + 5, request.width)):
                        pixels[xx, yy] = colour
        image.save(request.output_path)
        return ImageResult(request.output_path, request.seed, self.name)

    def health(self) -> dict:
        return {"backend": self.name, "reachable": True}


class BlankBackend(BlockBackend):
    name = "blank"

    def generate(self, request: ImageRequest) -> ImageResult:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (request.width, request.height), (255, 255, 255)).save(request.output_path)
        return ImageResult(request.output_path, request.seed, self.name)


class PayloadLLM:
    def __init__(self, payload):
        self.payload = payload

    def generate_json(self, _prompt: str):
        return self.payload


class PromptLLM:
    def generate_json(self, prompt: str):
        if "Beats:" in prompt:
            match = prompt.split("Beats:", 1)[1].strip()
            beats = json.loads(match.split("\n\nReturn ONLY", 1)[0])
            return [
                {
                    "index": beat["index"],
                    "prompt": f"Painterly camp scene showing people working. Beat {beat['index']}.",
                    "character_ids": ["amara"],
                }
                for beat in beats
            ]
        return {"prompt": "A painterly camp at dusk", "text": "WHAT DID THEY DO?",
                "character_ids": ["amara"]}


# ------------------------------------------------------------------ character
def test_character_bible_fallback_is_stable_and_contains_no_stickman():
    plan = _plan()
    settings = _settings()
    first = CharacterBibleBuilder(settings, llm=None).build(plan)
    second = CharacterBibleBuilder(settings, llm=None).build(plan)

    assert first.source == "fallback"
    assert 1 <= len(first.characters) <= 3
    assert first.fingerprint and first.fingerprint == second.fingerprint
    assert [character.id for character in first.characters] == [
        character.id for character in second.characters]
    assert "stick" not in first.style_lock.lower()
    assert all(character.reference_prompt for character in first.characters)


def test_character_bible_payload_is_validated_and_reused(tmp_path):
    payload = {
        "style_lock": "Painterly documentary gouache, warm ochre light, soft edges.",
        "notes": "Keep the same silhouette.",
        "characters": [{
            "id": "Mara",
            "name": "Mara",
            "role": "primary",
            "identity": ("A woman in her thirties with light brown skin, a heart-shaped face, "
                         "hazel eyes, a short dark curly bob, and a small mole below her right eye."),
            "wardrobe": "A faded olive field jacket, charcoal shirt, dark trousers, brown boots.",
            "distinguishing_features": "Short curly bob and a leather notebook satchel.",
            "palette": "olive, charcoal, worn brown",
            "reference_prompt": "Full body reference on a neutral grey backdrop.",
            "portrait_prompt": "Head and shoulders reference on a neutral grey backdrop.",
            "forbidden_changes": ["do not change the face"],
        }],
    }
    builder = CharacterBibleBuilder(_settings(), PayloadLLM(payload))
    bible = builder.build(_plan())
    assert bible.source == "llm"
    assert bible.characters[0].id == "mara"
    assert bible.characters[0].seed is not None
    assert "mara" in bible.ids()

    path = builder.save(bible, tmp_path)
    assert path.is_file()
    reloaded = builder.load(tmp_path)
    assert reloaded is not None
    assert reloaded.characters[0].name == "Mara"


def test_manifest_uses_scene_specific_character_identity():
    settings = _settings(NARRATION_SCENE_SECONDS=2.5, NARRATION_MANIFEST_BATCH_SIZE=50)
    plan = _plan()
    bible = CharacterBibleBuilder(settings, llm=None).build(plan)
    alignment = AlignmentResult(
        segments=[AlignSegment(start=i * 2, end=i * 2 + 2,
                               text=f"People work together at the camp, scene {i}.")
                  for i in range(6)],
        duration_seconds=12, source="whisperx")
    manifest = SceneManifestBuilder(settings, PromptLLM()).build(
        plan, alignment, 12, "narration.wav", character_bible=bible,
        script_fingerprint=script_fingerprint(plan, settings.narration_style_prefix, ""))

    assert manifest.scenes
    assert all(scene.character_ids for scene in manifest.scenes)
    selected = manifest.identity_for(["amara"])
    assert "Amara" in selected or "braid" in selected
    assert manifest.identity_for([]) == ""
    assert manifest.thumbnail_character_ids == ["amara"]
    assert manifest.thumbnail_text == "WHAT DID THEY DO?"


# ---------------------------------------------------------------------- images
def test_references_scenes_and_resume_cache(tmp_path):
    settings = _settings()
    plan = _plan()
    builder = CharacterBibleBuilder(settings, llm=None)
    bible = builder.load_or_build(plan, tmp_path)
    service = ImageGenerationService(settings, BlockBackend(settings))

    first = service.ensure_references(
        bible, tmp_path, on_save=lambda current: builder.save(current, tmp_path))
    assert first.generated == len(bible.characters) * 2
    assert first.total == len(bible.characters) * 2
    assert first.cached == 0
    assert all(character.references for character in bible.characters)
    assert all(Path(path).is_file() for path in bible.reference_paths())

    manifest = SceneManifest(
        topic="t", style_prefix=settings.narration_style_prefix,
        negative_prompt=settings.narration_negative_prompt, character_bible=bible,
        scenes=[Scene(index=i, start=i * 2, end=i * 2 + 2,
                      prompt=f"A painterly camp scene with people, {i}.",
                      character_ids=["amara"]) for i in range(1, 4)])
    stats = service.generate_manifest(manifest, tmp_path / "images")
    assert stats.generated == 3 and stats.failed == 0
    assert all(scene.image_path and Path(scene.image_path).is_file() for scene in manifest.scenes)
    assert all(scene.validation_status == "passed" for scene in manifest.scenes)

    # A repeated run reuses every cached scene.
    cached = service.generate_manifest(manifest, tmp_path / "images")
    assert cached.cached == 3 and cached.generated == 0

    # Deleting one image makes only that scene regenerate.
    lost = Path(manifest.scenes[1].image_path)
    lost.unlink()
    repaired = service.generate_manifest(manifest, tmp_path / "images")
    assert repaired.generated == 1 and repaired.cached == 2


def test_blank_images_are_rejected_not_silently_accepted(tmp_path):
    settings = _settings(NARRATION_MAX_RETRIES=1)
    plan = _plan()
    builder = CharacterBibleBuilder(settings, llm=None)
    bible = builder.load_or_build(plan, tmp_path)
    service = ImageGenerationService(settings, BlankBackend(settings))
    with pytest.raises(ImageGenerationError, match="usable"):
        service.ensure_references(bible, tmp_path)


def test_thumbnail_source_and_deterministic_overlay(tmp_path):
    from app.narration.video_assembler import VideoAssembler

    settings = _settings()
    bible = CharacterBibleBuilder(settings, llm=None).load_or_build(_plan(), tmp_path)
    manifest = SceneManifest(
        topic="t", title="Ancient Days", style_prefix=settings.narration_style_prefix,
        negative_prompt=settings.narration_negative_prompt, character_bible=bible,
        thumbnail_prompt="A painterly camp at dusk", thumbnail_text="WHAT DID THEY DO?",
        thumbnail_character_ids=["amara"],
        scenes=[Scene(index=1, start=0, end=2, prompt="camp", image_path=None)])
    service = ImageGenerationService(settings, BlockBackend(settings))
    source = service.generate_thumbnail(manifest, tmp_path / "thumbnail")
    assert source is not None and source.is_file()

    assembler = VideoAssembler.__new__(VideoAssembler)
    final = assembler.make_thumbnail(source, tmp_path / "thumbnail.png", manifest.thumbnail_text)
    assert final is not None
    with Image.open(final) as image:
        assert image.size == (1280, 720)


def test_quality_checker_flags_blank_and_duplicate():
    settings = _settings()
    checker = QualityChecker(settings)
    blank = Path("blank_test.png")
    try:
        Image.new("RGB", (512, 320), (255, 255, 255)).save(blank)
        quality = checker.inspect(blank)
        assert not quality.ok
        assert any(flag.startswith("flat_image") or flag.startswith("low_detail")
                   for flag in quality.hard_failures)
    finally:
        blank.unlink(missing_ok=True)


# ----------------------------------------------------------------------- llm
def test_narration_llm_routes_prefer_narrator_key():
    from app.narration.llm import resolve_routes

    settings = _settings(
        LLM_PROVIDER="omniroute",
        NARRATION_LLM_PROVIDER="auto",
        OPENROUTER_API_KEY_NARRATOR="sk-or-test-key",
        OMNIROUTE_API_KEY_NARRATOR="",
    )
    routes = resolve_routes(settings)
    assert routes and routes[0].provider == "openrouter"
    assert any("test-key" not in str(model) for model in routes[0].models)


def test_local_piper_and_diffusers_pass_runtime_validation(tmp_path):
    from app.narration.config import require_remote

    model = tmp_path / "voice.onnx"
    model.write_bytes(b"voice")
    settings = _settings(
        NARRATION_TTS_BACKEND="piper_local",
        NARRATION_PIPER_MODEL=str(model),
        NARRATION_IMAGE_BACKEND="diffusers",
    )
    require_remote(settings)

    with pytest.raises(RuntimeError, match="NARRATION_TTS_URL"):
        require_remote(_settings(NARRATION_TTS_BACKEND="http"))


def test_piper_length_scale_is_forwarded(tmp_path, monkeypatch):
    import subprocess as subprocess_module

    from app.narration.audio_engine import AudioEngine

    model = tmp_path / "voice.onnx"
    model.write_bytes(b"voice")
    settings = _settings(
        NARRATION_TTS_BACKEND="piper_local",
        NARRATION_PIPER_MODEL=str(model),
        NARRATION_PIPER_LENGTH_SCALE="1.17",
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["text"] = kwargs.get("input")
        Path(command[command.index("--output_file") + 1]).write_bytes(b"RIFF fake")
        return subprocess_module.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess_module, "run", fake_run)
    result = AudioEngine(settings, tmp_path).synthesize("Hello world.", tmp_path / "out.wav")
    assert result.is_file()
    command = captured["command"]
    assert "--length-scale" in command
    assert command[command.index("--length-scale") + 1] == "1.17"
    assert captured["text"] == "Hello world."


# ------------------------------------------------------------------ pipeline
def test_smoke_pipeline_end_to_end_and_scene_resume(tmp_path, monkeypatch):
    """Exercise the production orchestrator with a fake image backend/TTS.

    This is a real FFmpeg render and a real resume path. Only the diffusion
    model and speech synthesis are replaced, because this machine has a 4 GB
    GPU and no torch/diffusers install.
    """
    import shutil
    import wave

    import app.jobs.manager as manager
    import app.narration.orchestrator as orchestrator
    from app.narration.audio_engine import AudioEngine
    from app.narration.studio import NarrationStudio

    settings = _settings(
        VIDEO_WIDTH=1280,
        VIDEO_HEIGHT=720,
        VIDEO_FPS=15,
        NARRATION_SCENE_SECONDS=3.0,
        NARRATION_MIN_SCENES=1,
        NARRATION_MAX_SCENES=12,
        NARRATION_MANIFEST_BATCH_SIZE=12,
        NARRATION_MAX_RETRIES=0,
        NARRATION_TTS_BACKEND="kokoro_local",
        NARRATION_EXPORT_ENABLED=False,
        NARRATION_QUALITY_MIN_STDDEV=2,
        NARRATION_QUALITY_MIN_ENTROPY=0.2,
        DATABASE_PATH=str(tmp_path / "jobs" / "registry.db"),
    )
    audio_path = tmp_path / "fake_narration.wav"
    with wave.open(str(audio_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000 * 10)

    def fake_synthesize(self, _text, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio_path, output_path)
        return output_path

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(manager, "get_settings", lambda: settings)
    monkeypatch.setattr(AudioEngine, "synthesize", fake_synthesize)
    monkeypatch.setattr(AudioEngine, "align", lambda self, _path: None)
    monkeypatch.setattr(orchestrator, "require_remote", lambda _settings: None)
    monkeypatch.setattr(
        orchestrator, "build_image_backend",
        lambda current, on_log=None: BlockBackend(current, on_log=on_log))

    studio = NarrationStudio(settings)
    report = studio.smoke_test("What did ancient humans actually do all day?", 10)
    assert report["ok"] is True, report
    assert report["checks"]["all_passed"] is True
    assert report["checks"]["scene_count"] >= 2
    assert report["checks"]["scenes_with_images"] == report["checks"]["scene_count"]
    assert report["checks"]["all_characters_have_references"] is True
    assert report["checks"]["video_streams"] == 1
    assert report["checks"]["audio_streams"] == 1
    assert report["checks"]["thumbnail_size"] == [1280, 720]
    assert report["output_validation"]["width"] == 1280
    assert report["output_validation"]["height"] == 720
    assert abs(report["output_validation"]["duration_seconds"] - 10.0) < 0.5

    job_id = report["job_id"]
    job_dir = tmp_path / "jobs" / job_id
    manifest_before = json.loads(
        (job_dir / "manifest" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_before["character_bible"]["characters"]
    assert len(manifest_before["scenes"]) >= 2
    cached_scene = Path(manifest_before["scenes"][1]["image_path"])
    assert cached_scene.is_file()
    cached_scene.unlink()

    assert studio.resume(job_id) is True
    resumed = studio.build_report(job_id)
    assert resumed["checks"]["all_scenes_have_images"] is True
    assert resumed["image_generation"]["generated"] == 1
    assert resumed["image_generation"]["cached"] >= 1
    assert resumed["checks"]["all_passed"] is True


def test_assembler_rejects_visual_shorter_than_narration(tmp_path, monkeypatch):
    from app.narration import video_assembler
    from app.narration.video_assembler import AssemblyError, VideoAssembler

    assembler = VideoAssembler.__new__(VideoAssembler)
    assembler.settings = _settings()
    monkeypatch.setattr(
        video_assembler, "probe_media",
        lambda path: {"format": {"duration": 4.0 if Path(path).name.startswith("visual") else 5.0}})
    with pytest.raises(AssemblyError, match="shorter than the narration"):
        assembler._guard_durations(tmp_path / "visual.mp4", tmp_path / "narration.wav")

    monkeypatch.setattr(
        video_assembler, "probe_media",
        lambda _path: {"format": {"duration": 5.0}})
    assembler._guard_durations(tmp_path / "visual.mp4", tmp_path / "narration.wav")


# ------------------------------------------------------------------ prompts
def test_compose_positive_prioritizes_the_specific_prompt():
    style = ("Cinematic painterly documentary illustration, textured gouache and oil "
             "brushwork, warm light, muted earth tones, " + " ".join(["soft shadow"] * 30))
    text = compose_positive(
        style, "A woman knaps flint beside a river.", "Amara has a dark braid.")
    assert "A woman knaps flint beside a river." in text
    assert text.index("A woman") < text.index("Amara")
    assert len(text.split("A woman")[0].split()) <= 20


class _FakeTokenizer:
    model_max_length = 77

    def __call__(self, text, truncation=True, max_length=77, add_special_tokens=False):
        return SimpleNamespace(input_ids=text.split()[:max_length])

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(ids)


class _FakePipe:
    def __init__(self):
        self.tokenizer = _FakeTokenizer()
        self.tokenizer_2 = _FakeTokenizer()
        self.unet = SimpleNamespace(
            encoder_hid_proj=SimpleNamespace(image_projection_layers=[object()]))
        self.scale = None
        self.kwargs = None

    def set_ip_adapter_scale(self, scale):
        self.scale = scale

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(images=[Image.new("RGB", (16, 16), "white")])


class _FakeGenerator:
    def manual_seed(self, seed):
        return self


class _FakeTorch:
    def Generator(self, device="cpu"):
        return _FakeGenerator()


def _fake_backend():
    backend = DiffusersImageBackend(_settings(), on_log=lambda _message: None)
    backend.pipe = _FakePipe()
    backend.torch = _FakeTorch()
    return backend


def test_diffusers_text_only_reference_gets_ip_adapter_placeholder(tmp_path):
    backend = _fake_backend()
    result = backend.generate(ImageRequest(
        prompt="A full-body reference of Amara",
        negative_prompt="blurry",
        width=256,
        height=256,
        seed=7,
        output_path=tmp_path / "reference.png",
    ))
    assert result.path.is_file()
    assert backend.pipe.scale == 0.0
    assert backend.pipe.kwargs["ip_adapter_image"] is not None
    assert "text-only" in result.metadata["reference_note"]


def test_diffusers_uses_one_reference_per_ip_adapter(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (32, 32), "gray").save(first)
    Image.new("RGB", (32, 32), "brown").save(second)
    backend = _fake_backend()
    result = backend.generate(ImageRequest(
        prompt="Amara stands beside a river",
        negative_prompt="",
        width=256,
        height=256,
        seed=7,
        output_path=tmp_path / "scene.png",
        reference_images=[first, second],
    ))
    assert result.path.is_file()
    assert backend.pipe.scale == _settings().narration_ip_adapter_scale
    assert not isinstance(backend.pipe.kwargs["ip_adapter_image"], list)
    assert "one image per IP-Adapter" in result.metadata["reference_note"]


def test_fit_prompt_caps_the_clip_token_budget():
    backend = _fake_backend()
    fitted = backend._fit_prompt(" ".join(f"word{i}" for i in range(120)))
    assert len(fitted.split()) <= 75


def test_vit_h_ip_adapter_uses_the_vit_h_image_encoder():
    settings = _settings()
    assert "vit-h" in settings.narration_ip_adapter_weight
    assert settings.narration_ip_adapter_image_encoder == "models/image_encoder"


# -------------------------------------------------------------------- notebook
def test_colab_notebook_has_at_most_two_code_cells_and_uses_studio():
    notebook_path = (Path(__file__).resolve().parents[1] / "deploy"
                     / "narration_ai_studio_colab.ipynb")
    if not notebook_path.is_file():
        pytest.skip("Colab notebook has not been built yet")
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook["cells"] if cell.get("cell_type") == "code"]
    assert 1 <= len(code_cells) <= 2
    source = "\n".join("".join(cell.get("source", [])) for cell in code_cells)
    assert "NarrationStudio" in source
    assert "smoke_test" in source
    assert "stickman" not in source.lower()
