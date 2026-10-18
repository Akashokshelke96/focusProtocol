"""CLI for driving the pod batch server from the local machine.

Usage examples::

    # Submit topics; the pod's LLM writes the scripts.
    python main.py narration-batch --topics "roman roads, silk road" --duration 10 --wait

    # Submit already-approved scripts.
    python main.py narration-batch --scripts workspace/batches/drafts --wait --download output\\narration

    # Attach to a running batch and stream its per-video progress.
    python main.py narration-batch --status 20260101_120000 --wait

    # List batches on the pod.
    python main.py narration-batch --list
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from app.config.logging_config import get_logger
from app.config.settings import get_settings
from app.narration.models import ScriptPlan
from app.narration.pod_client import PodBatchClient, PodClientError

logger = get_logger("narration.batch_cli")

PHASE_ORDER = ("SCRIPT", "TTS", "ALIGN", "MANIFEST", "IMAGES", "RENDER", "PACKAGE")
_STAGE_MARK = {"done": "OK", "failed": "XX", "pending": ".."}


def load_items(args) -> list[dict]:
    items: list[dict] = []
    if getattr(args, "items", None):
        data = json.loads(Path(args.items).read_text(encoding="utf-8"))
        records = data.get("items") if isinstance(data, dict) else data
        if not isinstance(records, list):
            raise ValueError("--items file must be a JSON list or an object with an 'items' list")
        items.extend(records)
    if getattr(args, "scripts", None):
        for path in sorted(Path(args.scripts).rglob("script.json")):
            plan = ScriptPlan.model_validate_json(path.read_text(encoding="utf-8"))
            items.append({"topic": plan.topic, "title": plan.title, "script": plan.script,
                          "duration_minutes": args.duration})
    if getattr(args, "topics", None):
        for topic in [t.strip() for t in args.topics.split(",") if t.strip()]:
            items.append({"topic": topic, "duration_minutes": args.duration})
    return items


def render_status(state: dict) -> str:
    lines = [f"batch {state.get('batch_id')} | status={state.get('status')} "
             f"| phase={state.get('phase')} | elapsed={state.get('elapsed_seconds', '-')}s"]
    for video in state.get("videos", []):
        stages = " ".join(
            f"{phase}:{_STAGE_MARK.get(video['stages'].get(phase), '??')}" for phase in PHASE_ORDER)
        line = f"  [{video['index']:>2}] {video.get('id', '')}  {stages}"
        if video.get("error"):
            line += f"  error={video['error']}"
        lines.append(line)
    return "\n".join(lines)


def run(args) -> int:
    settings = get_settings()
    try:
        client = PodBatchClient(settings)
    except PodClientError as error:
        logger.error("%s", error)
        return 1

    try:
        if getattr(args, "list", False):
            for batch in client.list_batches():
                print(f"{batch['batch_id']} | {batch.get('status')} | phase={batch.get('phase')} "
                      f"| videos={batch.get('videos')}")
            return 0

        if getattr(args, "status", None):
            print(render_status(client.status(args.status)))
            return 0

        items = load_items(args)
        if not items:
            logger.error("Nothing to submit: pass --topics, --items, or --scripts")
            return 1
        for item in items:
            item.setdefault("duration_minutes", args.duration)
        result = client.submit(items, batch_id=getattr(args, "batch_id", "") or "")
        batch_id = result["batch_id"]
        logger.info("Submitted batch %s (%s videos)", batch_id, result.get("videos"))

        if not getattr(args, "wait", False):
            print(batch_id)
            return 0

        def on_update(state: dict) -> None:
            print(render_status(state))

        print(f"Waiting for batch {batch_id}...")
        state = client.wait(batch_id, poll_seconds=getattr(args, "poll", None), on_update=on_update)
        print(render_status(state))

        if getattr(args, "download", None):
            files = client.download_all(batch_id, Path(args.download))
            for path in files:
                print(f"downloaded {path}")

        return 0 if state.get("status") == "completed" else 1
    except PodClientError as error:
        logger.error("Batch error: %s", error)
        return 1
