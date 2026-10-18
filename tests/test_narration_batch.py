"""Unit tests for the pod batch system (engine state, CLI, client, workflow)."""
from __future__ import annotations
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config.settings import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


# ------------------------------------------------------------------ workflow
def test_flux_workflow_and_sidecar_are_valid():
    root = Path(__file__).resolve().parents[1]
    workflow = root / "workflows" / "flux_schnell_api.json"
    sidecar = root / "workflows" / "flux_schnell_api.map.json"
    assert workflow.is_file() and sidecar.is_file()
    graph = json.loads(workflow.read_text(encoding="utf-8"))
    mapping = json.loads(sidecar.read_text(encoding="utf-8"))
    # Every mapped node must exist in the graph.
    for key, (node_id, _input) in mapping.items():
        assert node_id in graph, f"{key} points at a missing node {node_id}"


# ------------------------------------------------------------------ input map
def test_resolve_input_map_uses_sidecar(tmp_path):
    from app.narration.config import resolve_comfy_input_map
    workflow = tmp_path / "wf.json"
    workflow.write_text("{}", encoding="utf-8")
    (tmp_path / "wf.map.json").write_text(
        json.dumps({"positive_prompt": ["10", "text"]}), encoding="utf-8")
    mapping = resolve_comfy_input_map(_settings(COMFY_INPUT_MAP=""), workflow)
    assert mapping["positive_prompt"] == ["10", "text"]
    assert mapping["negative_prompt"] == ["5", "text"]  # default retained


def test_resolve_input_map_env_overrides_sidecar(tmp_path):
    from app.narration.config import resolve_comfy_input_map
    workflow = tmp_path / "wf.json"
    workflow.write_text("{}", encoding="utf-8")
    (tmp_path / "wf.map.json").write_text(
        json.dumps({"seed": ["10", "seed"]}), encoding="utf-8")
    mapping = resolve_comfy_input_map(_settings(COMFY_INPUT_MAP=json.dumps({"seed": ["3", "seed"]})), workflow)
    assert mapping["seed"] == ["3", "seed"]


# ------------------------------------------------------------------ engine
def test_batch_engine_init_state_shape():
    from app.narration.pod.batch_engine import BatchEngine, PHASES
    engine = BatchEngine.__new__(BatchEngine)
    engine.settings = _settings(NARRATION_TARGET_DURATION_MINUTES=10)
    state = engine._init_state([{"topic": "roman roads", "title": "Roads"}], "b1")
    assert state["batch_id"] == "b1"
    assert state["phase"] == PHASES[0]
    video = state["videos"][0]
    assert video["stages"] == {phase: "pending" for phase in PHASES}
    assert video["duration_minutes"] == 10.0


def test_batch_engine_slug():
    from app.narration.pod.batch_engine import _slug
    assert _slug("The Rise & Fall!") == "the_rise_fall"
    assert _slug("") == "video"


# ------------------------------------------------------------------ client
def test_pod_client_requires_url():
    from app.narration.pod_client import PodBatchClient, PodClientError
    with pytest.raises(PodClientError):
        PodBatchClient(_settings(POD_BATCH_URL=""))


def test_pod_client_builds_from_settings():
    from app.narration.pod_client import PodBatchClient
    client = PodBatchClient(_settings(POD_BATCH_URL="https://x-8000.proxy.runpod.net/", POD_BATCH_TOKEN="t"))
    assert client.base_url == "https://x-8000.proxy.runpod.net"
    assert client.session.headers["X-Batch-Token"] == "t"
    assert client.is_terminal({"status": "completed"})
    assert not client.is_terminal({"status": "running"})


# ------------------------------------------------------------------ CLI
def test_load_items_from_topics():
    from app.narration.batch_cli import load_items
    args = SimpleNamespace(items=None, scripts=None, topics="A, B ,", duration=12)
    items = load_items(args)
    assert [item["topic"] for item in items] == ["A", "B"]
    assert items[0]["duration_minutes"] == 12


def test_load_items_from_scripts(tmp_path):
    from app.narration.batch_cli import load_items
    script_dir = tmp_path / "vid1" / "script"
    script_dir.mkdir(parents=True)
    (script_dir / "script.json").write_text(json.dumps({
        "topic": "t", "title": "Title", "script": "word " * 60, "approved": True,
    }), encoding="utf-8")
    args = SimpleNamespace(items=None, scripts=str(tmp_path), topics=None, duration=10)
    items = load_items(args)
    assert len(items) == 1
    assert items[0]["title"] == "Title"


def test_render_status_lists_stages():
    from app.narration.batch_cli import render_status
    state = {
        "batch_id": "b1", "status": "running", "phase": "TTS", "elapsed_seconds": 12.0,
        "videos": [{"index": 0, "id": "001_x", "title": "X", "duration_minutes": 10,
                    "stages": {"SCRIPT": "done", "TTS": "failed"}, "error": "TTS: boom"}],
    }
    text = render_status(state)
    assert "b1" in text
    assert "SCRIPT:OK" in text
    assert "TTS:XX" in text
    assert "boom" in text


# ------------------------------------------------------------------ server
def test_server_exposes_app():
    pytest.importorskip("fastapi")
    from app.narration.pod import server
    assert server.app is not None
    routes = {route.path for route in server.app.routes}
    assert "/batch" in routes
    assert "/batch/{batch_id}" in routes
    assert "/health" in routes
