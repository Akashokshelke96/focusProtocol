"""Script generation (OpenRouter via the shared provider) + local approval gate."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from app.config.logging_config import get_logger
from app.config.settings import Settings
from app.narration.config import target_word_range
from app.narration.models import ScriptPlan
from app.narration.prompts import NARRATION_SCRIPT_PROMPT

logger = get_logger("narration.script")

WORDS_PER_MINUTE = 150.0


class ScriptDeclined(RuntimeError):
    """Raised when the operator rejects the generated script."""


class ScriptGenerator:
    """Generates a narration script and drives the one-time approval gate."""

    def __init__(self, settings: Settings, llm: Any):
        self.settings = settings
        self.llm = llm

    def generate(self, topic: str, duration_minutes: float, variation: int = 0) -> ScriptPlan:
        """Ask the LLM for a full narration script for the topic."""
        word_min, word_target, word_max = target_word_range(duration_minutes)
        prompt = NARRATION_SCRIPT_PROMPT.format(
            channel=self.settings.channel_brand_name,
            duration_minutes=f"{duration_minutes:g}",
            topic=topic.strip(),
            word_min=word_min,
            word_target=word_target,
            word_max=word_max,
        )
        if variation:
            prompt += (
                f"\n\nThis is regeneration attempt #{variation}: take a noticeably different "
                "angle, structure, and examples while keeping the same topic and constraints."
            )

        data = self.llm.generate_json(prompt)
        if not isinstance(data, dict):
            raise ValueError("Script generator expected a JSON object from the LLM")

        script = str(data.get("script") or "").strip()
        if len(script.split()) < 50:
            raise ValueError("LLM returned an unusably short script")

        word_count = len(script.split())
        plan = ScriptPlan(
            topic=topic.strip(),
            title=str(data.get("title") or topic).strip(),
            hook=str(data.get("hook") or "").strip(),
            script=script,
            word_count=word_count,
            estimated_duration_seconds=round(word_count / WORDS_PER_MINUTE * 60, 2),
        )
        logger.info(
            "Script generated: %s words (~%.1f min)",
            plan.word_count,
            plan.estimated_duration_seconds / 60,
        )
        return plan

    def run_gate(
        self,
        topic: str,
        duration_minutes: float,
        job_dir: Path,
        auto_approve: bool = False,
        input_fn: Callable[[str], str] = input,
    ) -> ScriptPlan:
        """Generate, present, and (optionally) approve the script.

        Choices: Approve, Edit (open the saved .txt, then reload), Regenerate,
        Quit. ``auto_approve`` skips interaction for automation.
        """
        job_dir = Path(job_dir)
        (job_dir / "script").mkdir(parents=True, exist_ok=True)
        plan = self.generate(topic, duration_minutes)

        if auto_approve:
            plan.approved = True
            self.save(plan, job_dir)
            logger.info("Script auto-approved (--yes)")
            return plan

        variation = 0
        while True:
            self.save(plan, job_dir)
            self._print_script(plan, job_dir)
            choice = (input_fn(
                "Script options -> [a]pprove / [e]dit / [r]egenerate / [q]uit: "
            ) or "").strip().lower()

            if choice in ("a", "approve", ""):
                plan.approved = True
                self.save(plan, job_dir)
                logger.info("Script approved")
                return plan
            if choice in ("e", "edit"):
                self._edit(plan, job_dir)
                plan.edited = True
                continue
            if choice in ("r", "regenerate"):
                variation += 1
                plan = self.generate(topic, duration_minutes, variation=variation)
                continue
            if choice in ("q", "quit", "cancel"):
                raise ScriptDeclined("Script rejected by operator")
            print("Please enter a, e, r, or q.")

    def save(self, plan: ScriptPlan, job_dir: Path) -> Path:
        """Persist the plan as script.json and a human-editable script.txt."""
        script_dir = Path(job_dir) / "script"
        script_dir.mkdir(parents=True, exist_ok=True)
        plan.word_count = len(plan.script.split())
        plan.estimated_duration_seconds = round(plan.word_count / WORDS_PER_MINUTE * 60, 2)
        json_path = script_dir / "script.json"
        json_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        (script_dir / "script.txt").write_text(plan.script, encoding="utf-8")
        return json_path

    @staticmethod
    def load(job_dir: Path) -> Optional[ScriptPlan]:
        path = Path(job_dir) / "script" / "script.json"
        if not path.is_file():
            return None
        return ScriptPlan.model_validate_json(path.read_text(encoding="utf-8"))

    def _print_script(self, plan: ScriptPlan, job_dir: Path) -> None:
        text_path = Path(job_dir) / "script" / "script.txt"
        print("\n" + "=" * 70)
        print(f"TITLE: {plan.title}")
        print(f"WORDS: {plan.word_count}  (~{plan.estimated_duration_seconds/60:.1f} min)")
        print(f"FULL TEXT: {text_path}")
        print("=" * 70)
        print(plan.script)
        print("=" * 70 + "\n")

    def _edit(self, plan: ScriptPlan, job_dir: Path) -> None:
        text_path = Path(job_dir) / "script" / "script.txt"
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        try:
            if os.name == "nt" and not editor:
                os.startfile(str(text_path))  # noqa: S606 - user-chosen local editor
            else:
                subprocess.Popen([editor or "vi", str(text_path)])
        except Exception as error:  # pragma: no cover - depends on local editor
            logger.warning("Could not open an editor automatically: %s", error)
        input("Edit the file above, save it, then press Enter to reload...")
        plan.script = text_path.read_text(encoding="utf-8").strip()
        logger.info("Script reloaded after edit (%s words)", len(plan.script.split()))
