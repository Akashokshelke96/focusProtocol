"""Unit tests for the narrated pipeline's deterministic logic."""
import json
import re

import pytest

from app.config.settings import Settings
from app.narration.audio_engine import AudioEngine, _parse_alignment
from app.narration.comfy_client import ComfyUIClient
from app.narration.models import AlignSegment, AlignmentResult, ScriptPlan
from app.narration.scene_manifest import SceneManifestBuilder, compose_positive
from app.narration.script_generator import ScriptGenerator
from app.utils.ffmpeg import find_ffmpeg


SCRIPT = (
    "Elephants have never been farmed at scale for meat, and the reasons run deep. "
    "Their bodies convert food into muscle painfully slowly, so a herd takes a decade to grow. "
    "They are intelligent, social animals that resist the confinement any farm would demand. "
    "Across cultures they were hunted for ivory, never husbanded for the dinner table. "
    "What we eat is shaped by economics, biology, and the stories we tell about animals. "
    "That is why the elephant stayed off the menu while the cow did not."
)


class FakeLLM:
    """Deterministic stand-in for GeminiProvider.generate_json."""

    def generate_json(self, prompt: str):
        if "narration-only spoken script" in prompt:
            return {"title": "Why We Do Not Eat Elephants", "hook": "Have you ever wondered?",
                    "script": SCRIPT}
        if "Beats:" in prompt:
            match = re.search(r"(\[\{.*?\}\])", prompt, re.S)
            beats = json.loads(match.group(1)) if match else []
            return [{"index": beat["index"], "prompt": f"cinematic shot {beat['index']}"} for beat in beats]
        if "high-CTR" in prompt:
            return {"prompt": "a lone elephant at dusk, dramatic light"}
        return {"title": "t", "description": "d", "tags": []}


def _settings(**overrides):
    return Settings(_env_file=None, **overrides)


# ------------------------------------------------------------------ script
def test_script_gate_auto_approve_saves_and_reloads(tmp_path):
    generator = ScriptGenerator(_settings(), FakeLLM())
    plan = generator.run_gate("Why don't we eat elephants?", 1, tmp_path, auto_approve=True)

    assert plan.approved is True
    assert plan.word_count >= 50
    assert plan.estimated_duration_seconds > 0

    reloaded = ScriptGenerator.load(tmp_path)
    assert reloaded is not None
    assert reloaded.approved is True
    assert reloaded.script == plan.script
    assert (tmp_path / "script" / "script.txt").is_file()


# ---------------------------------------------------------------- manifest
def test_manifest_windows_cover_timeline(tmp_path):
    settings = _settings(NARRATION_MIN_SCENES=4, NARRATION_MAX_SCENES=6,
                         NARRATION_SCENE_SECONDS=2.5, NARRATION_MANIFEST_BATCH_SIZE=3)
    builder = SceneManifestBuilder(settings, FakeLLM())
    plan = ScriptPlan(topic="Elephants", title="T", script=SCRIPT)
    alignment = AlignmentResult(
        segments=[
            AlignSegment(start=0, end=1.1, text="First sentence."),
            AlignSegment(start=1.1, end=2.2, text="Second sentence."),
            AlignSegment(start=2.2, end=4.5, text="Third sentence."),
            AlignSegment(start=4.5, end=6.0, text="Fourth sentence."),
            AlignSegment(start=6.0, end=8.0, text="Fifth sentence."),
            AlignSegment(start=8.0, end=10.0, text="Sixth sentence."),
            AlignSegment(start=10.0, end=12.0, text="Seventh sentence."),
        ], duration_seconds=12.0, source="whisperx")

    manifest = builder.build(plan, alignment, 12.0, "narration.wav")

    assert 4 <= len(manifest.scenes) <= 7
    assert manifest.scenes[0].start == 0
    assert abs(manifest.scenes[-1].end - 12.0) < 1e-6
    assert all(scene.prompt for scene in manifest.scenes)
    assert manifest.thumbnail_prompt
    assert manifest.thumbnail_text == "WHAT DID THEY DO?"
    assert manifest.alignment_source == "whisperx"
    # Every scene window maps back to narration text from the alignment.
    joined = " ".join(scene.text for scene in manifest.scenes)
    assert joined == "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence. Sixth sentence. Seventh sentence."
    assert all(scene.end > scene.start for scene in manifest.scenes)


def test_manifest_scene_windows_do_not_duplicate_or_drop_aligned_text():
    windows = SceneManifestBuilder._time_windows(
        AlignmentResult(segments=[
            AlignSegment(start=0, end=1.2, text="A gathers roots."),
            AlignSegment(start=1.2, end=2.5, text="B sharpens a stone tool."),
            AlignSegment(start=2.5, end=3.7, text="C carries water home."),
            AlignSegment(start=3.7, end=5.0, text="D tends the fire."),
        ], duration_seconds=5.0),
        duration_seconds=5.0, scene_count=2, target_seconds=2.5,
    )
    narration = " ".join(text for _start, _end, text in windows).replace(".", "")
    assert narration == "A gathers roots B sharpens a stone tool C carries water home D tends the fire"
    assert windows[0][0] == 0.0
    assert windows[-1][1] == 5.0


def test_long_aligned_utterance_is_split_into_readable_shots():
    text = "At dawn the group leaves camp to gather roots while another hunter follows fresh tracks toward the river."
    windows = SceneManifestBuilder._time_windows(
        AlignmentResult(segments=[AlignSegment(start=0, end=10, text=text)], duration_seconds=10),
        duration_seconds=10, scene_count=4, target_seconds=2.5,
    )
    assert len(windows) >= 3
    assert " ".join(window[2] for window in windows) == text
    assert max(end - start for start, end, _text in windows) <= 3.6


def test_scene_windows_keep_silence_gaps_on_the_audio_timeline():
    windows = SceneManifestBuilder._time_windows(
        AlignmentResult(segments=[
            AlignSegment(start=0.8, end=2.0, text="The sun rises."),
            AlignSegment(start=4.5, end=5.5, text="The camp wakes."),
        ], duration_seconds=7.0),
        duration_seconds=7.0, scene_count=3, target_seconds=2.5,
    )
    assert windows[0][0] == 0.0
    assert windows[-1][1] == 7.0
    assert sum(end - start for start, end, _text in windows) == 7.0
    assert "The sun rises." in windows[0][2]
    assert "The camp wakes." in windows[-1][2]


def test_missing_scene_art_does_not_reuse_an_unrelated_image(tmp_path):
    from app.narration.models import Scene, SceneManifest
    from app.narration.orchestrator import NarrationOrchestrator
    from app.narration.video_assembler import AssemblyError

    image = tmp_path / "scene.png"
    image.write_bytes(b"available")
    manifest = SceneManifest(
        topic="t", scenes=[
            Scene(index=1, start=0, end=2, prompt="one", image_path=str(image)),
            Scene(index=2, start=2, end=4, prompt="two", image_path=None),
        ])
    with pytest.raises(AssemblyError, match="scene-specific image was produced"):
        NarrationOrchestrator._fill_missing_images(manifest)
    assert manifest.scenes[1].image_path is None


def test_thumbnail_crop_and_headline_are_written(tmp_path):
    from PIL import Image
    from app.narration.video_assembler import VideoAssembler

    source = tmp_path / "source.png"
    output = tmp_path / "thumbnail.png"
    Image.new("RGB", (900, 900), (90, 125, 80)).save(source)
    assembler = VideoAssembler.__new__(VideoAssembler)
    result = assembler.make_thumbnail(source, output, "ALL DAY?")
    assert result == output
    assert Image.open(output).size == (1280, 720)


def test_manifest_falls_back_when_llm_returns_nothing(tmp_path):
    class EmptyLLM(FakeLLM):
        def generate_json(self, prompt: str):
            if "Beats:" in prompt:
                return []
            return super().generate_json(prompt)

    settings = _settings(NARRATION_MIN_SCENES=4, NARRATION_MAX_SCENES=4)
    builder = SceneManifestBuilder(settings, EmptyLLM())
    plan = ScriptPlan(topic="Elephants", title="T", script=SCRIPT)
    manifest = builder.build(plan, AlignmentResult(duration_seconds=10.0, source="estimated"), 10.0)
    assert all(scene.prompt for scene in manifest.scenes)


# ------------------------------------------------------------ audio engine
def test_estimate_alignment_is_deterministic(tmp_path):
    engine = AudioEngine(_settings(), tmp_path)
    result = engine.estimate_alignment("One two three. Four five. Six.", 30.0)
    assert result.source == "estimated"
    assert len(result.segments) == 3
    assert abs(result.segments[-1].end - 30.0) < 0.01
    assert result.segments[0].start == 0.0


@pytest.mark.parametrize("payload", [
    {"segments": [{"start": 0, "end": 2, "text": "hi",
                   "words": [{"word": "hi", "start": 0, "end": 2, "score": 0.9}]}]},
    {"result": {"segments": [{"start": 1.5, "end": 3.0, "text": "yo"}]}},
    {"data": {"language": "en", "segments": [{"start": 0, "end": 1, "text": "a"}]}},
])
def test_parse_alignment_shapes(payload):
    result = _parse_alignment(payload)
    assert len(result.segments) == 1
    assert result.segments[0].end > result.segments[0].start


# --------------------------------------------------------------- comfy ui
COMFY_TEMPLATE = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
    "2": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "3": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 20, "cfg": 8.0,
                                               "sampler_name": "euler", "scheduler": "normal",
                                               "denoise": 1.0, "model": ["1", 0],
                                               "positive": ["4", 0], "negative": ["5", 0],
                                               "latent_image": ["2", 0]}},
    "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["1", 2]}},
    "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "scene", "images": ["6", 0]}},
}


def test_comfy_build_prompt_injects_tokens(tmp_path):
    workflow_path = tmp_path / "wf.json"
    workflow_path.write_text(json.dumps(COMFY_TEMPLATE), encoding="utf-8")
    settings = _settings(COMFY_WORKFLOW_PATH=str(workflow_path), COMFY_STEPS=6, COMFY_CFG=2.5)

    client = ComfyUIClient(settings)
    prompt, seed = client.build_prompt("POS", "NEG", 1024, 576, seed=123, filename_prefix="scene_0001")

    assert prompt["4"]["inputs"]["text"] == "POS"
    assert prompt["5"]["inputs"]["text"] == "NEG"
    assert prompt["3"]["inputs"]["seed"] == 123
    assert prompt["3"]["inputs"]["steps"] == 6
    assert prompt["3"]["inputs"]["cfg"] == 2.5
    assert prompt["2"]["inputs"]["width"] == 1024
    assert prompt["2"]["inputs"]["height"] == 576
    assert prompt["7"]["inputs"]["filename_prefix"] == "scene_0001"
    assert seed == 123
    # Template is never mutated by injection.
    assert client.template["4"]["inputs"]["text"] == ""


def test_compose_positive_handles_empty_parts():
    assert compose_positive("Style.", "Shot.") == "Style. Shot"
    assert compose_positive("", "Shot") == "Shot"
    assert compose_positive("Style", "") == "Style"


# --------------------------------------------------------------- assembler
@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_codec_args_selects_encoder():
    from app.narration.video_assembler import VideoAssembler

    assembler = VideoAssembler(_settings(NARRATION_VIDEO_ENCODER="h264_nvenc"))
    args = assembler._codec_args()
    assert args[:2] == ["-c:v", "h264_nvenc"]

    default = VideoAssembler(_settings(NARRATION_VIDEO_ENCODER=""))._codec_args()
    assert default[:2] == ["-c:v", "libx264"]
