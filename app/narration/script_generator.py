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

        try:
            data = self.llm.generate_json(prompt)
        except Exception as error:  # noqa: BLE001 - optional offline test fallback
            if not self.settings.narration_script_fallback:
                raise
            logger.warning("LLM script failed (%s); using local test script", error)
            return self._fallback_plan(topic, duration_minutes)
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

    def _fallback_plan(self, topic: str, duration_minutes: float) -> ScriptPlan:
        """Offline test script used only when NARRATION_SCRIPT_FALLBACK=true."""
        topic = (topic or "this subject").strip()
        paragraphs = [
            f"Most people think they understand {topic}. But the real story is stranger, and far "
            "more interesting. To see why, picture a lone traveler standing at a fork in an "
            "ancient road at dawn. The traveler carries a map, but the map is incomplete. That is "
            "where this story begins.",
            f"Every explanation of {topic} starts with a question, and the best questions sound "
            "almost too simple. What changed? Who benefited? What was lost? Imagine a crowded "
            "market at midday. A carved stone stands at the edge of the square, covered in names "
            "and numbers. Most "
            "people walk past it without looking. Then one detail catches the eye, and the whole "
            "picture begins to shift.",
            "Follow that detail into a firelit workshop, where a craftsperson bends over a wooden "
            "bench. Tools are scattered across the table: a chisel, a length of rope, a lump of "
            "clay. Outside, rain moves across the hills and a river rises under a wooden bridge. "
            "The craftsperson makes a small decision, the kind that seems unimportant at the time. "
            "Years later, that decision has changed how people travel, trade, build, and remember.",
            "This is how history usually works. Not with one grand moment, but with thousands of "
            "small choices that pile up until the world looks different. A family moves closer to "
            "a market. Each change is ordinary on its own. Together, they become a system that "
            "outlives the people who built it.",
            "So the next time you see an old road, a worn stone, or a map with a missing corner, "
            "look again. The surface is only the beginning. Beneath it is a story about people "
            "solving problems, making compromises, and leaving something behind. And once you "
            "notice that pattern, you will start seeing it everywhere.",
        ]
        script = " ".join(paragraphs)
        word_count = len(script.split())
        return ScriptPlan(
            topic=topic,
            title=f"The Hidden Story of {topic}"[:90],
            hook=f"Most people think they understand {topic}. They are missing the best part.",
            script=script,
            word_count=word_count,
            estimated_duration_seconds=round(word_count / WORDS_PER_MINUTE * 60, 2),
        )

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
