"""Headless ComfyUI client: native HTTP API + WebSocket execution watcher.

Talks to a ComfyUI instance exposed on a RunPod HTTP port:
- POST /prompt            queue a workflow (API format)
- GET  /history/{id}      poll results
- GET  /view              download generated images
- GET  /system_stats      health check
- ws://.../ws             live progress + execution_error interception

Live progress uses the WebSocket when ``websocket-client`` is installed;
otherwise (or on socket failure) the client transparently polls /history,
so image generation always completes without the GUI.
"""
from __future__ import annotations
import json
import random
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from app.config.logging_config import get_logger
from app.config.settings import Settings
from app.narration.config import derive_ws_url, resolve_comfy_input_map

logger = get_logger("narration.comfy")

try:  # optional dependency; polling works without it
    import websocket  # type: ignore
except Exception:  # pragma: no cover - import guard
    websocket = None


class ComfyUIError(RuntimeError):
    """Raised when the ComfyUI server cannot satisfy a request."""


class ComfyUIClient:
    def __init__(self, settings: Settings,
                 on_log: Optional[Callable[[str], None]] = None):
        self.settings = settings
        self.base_url = (settings.comfy_base_url or "").rstrip("/")
        self.ws_url = derive_ws_url(settings)
        self.input_map = resolve_comfy_input_map(settings, Path(settings.comfy_workflow_path))
        self.timeout = settings.comfy_timeout_seconds
        self.poll_interval = settings.comfy_poll_interval_seconds
        self.client_id = uuid.uuid4().hex
        self.session = requests.Session()
        self.template = self._load_template()
        self.on_log = on_log or (lambda message: logger.info(message))

    # ------------------------------------------------------------- workflow
    def _load_template(self) -> dict:
        path = Path(self.settings.comfy_workflow_path)
        if not path.is_file():
            raise ComfyUIError(f"ComfyUI workflow template not found: {path}")
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ComfyUIError(f"Invalid ComfyUI workflow JSON: {error}") from error
        if not isinstance(workflow, dict) or not workflow:
            raise ComfyUIError("ComfyUI workflow template must be a non-empty object")
        return workflow

    def build_prompt(self, positive: str, negative: str, width: int, height: int,
                     seed: Optional[int] = None, filename_prefix: str = "scene") -> tuple[dict, int]:
        """Inject prompt tokens and seed into the workflow template."""
        workflow = deepcopy(self.template)
        seed = random.randint(0, 2 ** 31 - 1) if seed is None else int(seed)
        values = {
            "positive_prompt": positive,
            "negative_prompt": negative,
            "seed": seed,
            "steps": self.settings.comfy_steps,
            "cfg": self.settings.comfy_cfg,
            "sampler_name": self.settings.comfy_sampler,
            "scheduler": self.settings.comfy_scheduler,
            "width": int(width),
            "height": int(height),
            "filename_prefix": filename_prefix,
        }
        for name, value in values.items():
            mapping = self.input_map.get(name)
            if not mapping:
                continue
            node_id, input_name = mapping
            node = workflow.get(node_id)
            if isinstance(node, dict) and isinstance(node.get("inputs"), dict):
                node["inputs"][input_name] = value
        return workflow, seed

    # ---------------------------------------------------------------- HTTP
    def health(self) -> dict:
        if not self.base_url:
            raise ComfyUIError("COMFY_BASE_URL is not configured")
        try:
            response = self.session.get(f"{self.base_url}/system_stats", timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            raise ComfyUIError(f"ComfyUI is unreachable at {self.base_url}: {error}") from error

    def queue_prompt(self, prompt: dict) -> str:
        try:
            response = self.session.post(
                f"{self.base_url}/prompt",
                json={"prompt": prompt, "client_id": self.client_id},
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            raise ComfyUIError(f"Failed to queue prompt: {error}") from error
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            # ComfyUI returns {error, node_errors} on validation failure.
            raise ComfyUIError(f"ComfyUI rejected the workflow: {json.dumps(payload)[:600]}")
        return prompt_id

    def history(self, prompt_id: str) -> dict:
        try:
            response = self.session.get(f"{self.base_url}/history/{prompt_id}", timeout=30)
            response.raise_for_status()
            return response.json() or {}
        except requests.RequestException as error:
            raise ComfyUIError(f"Failed to read history: {error}") from error

    def download_image(self, image_info: dict, dest_dir: Path) -> Path:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        params = {
            "filename": image_info.get("filename", ""),
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        }
        try:
            response = self.session.get(f"{self.base_url}/view", params=params, timeout=120)
            response.raise_for_status()
        except requests.RequestException as error:
            raise ComfyUIError(f"Failed to download image {params['filename']}: {error}") from error
        destination = dest_dir / (image_info.get("filename") or f"image_{uuid.uuid4().hex}.png")
        destination.write_bytes(response.content)
        return destination

    def interrupt(self) -> None:
        try:
            self.session.post(f"{self.base_url}/interrupt", timeout=15)
        except requests.RequestException as error:  # pragma: no cover - best effort
            logger.warning("Interrupt request failed: %s", error)

    # -------------------------------------------------------------- batch
    def generate_batch(
        self,
        requests_map: dict[str, dict],
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_image: Optional[Callable[[str, Path], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
        image_dir: Optional[Path] = None,
    ) -> dict[str, list[Path]]:
        """Queue every scene, then watch until all finish; retry failures.

        ``requests_map`` maps a key (scene id) to a ready workflow dict.
        Returns ``{key: [downloaded image paths]}``.
        """
        keys = list(requests_map.keys())
        total = len(keys)
        state: dict[str, dict[str, Any]] = {
            key: {"prompt_id": None, "images": [], "done": False, "error": None, "attempts": 0}
            for key in keys
        }
        image_dir = Path(image_dir) if image_dir else Path(".")

        for key in keys:
            self._submit(key, requests_map[key], state)

        max_retries = self.settings.narration_max_retries
        for attempt in range(max_retries + 1):
            self._watch_all(state, on_progress, on_image, on_error, image_dir, total)
            failed = [k for k in keys if not state[k]["done"]]
            if not failed or attempt == max_retries:
                break
            self.on_log(f"Retrying {len(failed)} failed scenes (attempt {attempt + 1}/{max_retries})")
            for key in failed:
                state[key]["error"] = None
                self._submit(key, requests_map[key], state)

        results: dict[str, list[Path]] = {}
        for key in keys:
            results[key] = state[key]["images"]
        finished = sum(1 for key in keys if state[key]["done"])
        self.on_log(f"ComfyUI batch complete: {finished}/{total} scenes")
        return results

    def _submit(self, key: str, prompt: dict, state: dict) -> None:
        try:
            prompt_id = self.queue_prompt(prompt)
            state[key].update(prompt_id=prompt_id, attempts=state[key]["attempts"] + 1)
        except ComfyUIError as error:
            state[key].update(error=str(error), done=False)
            logger.warning("Scene %s queue failed: %s", key, error)

    def _watch_all(self, state, on_progress, on_image, on_error, image_dir, total) -> None:
        pending = [k for k in state if not state[k]["done"]]
        if not pending:
            return
        if websocket is not None and self.ws_url:
            try:
                self._watch_ws(state, pending, on_progress, on_image, on_error, image_dir, total)
                if all(state[k]["done"] for k in state):
                    return
                logger.warning("WebSocket watch ended early; polling the remaining scenes")
            except Exception as error:  # noqa: BLE001 - fall back to polling
                logger.warning("WebSocket watch failed (%s); falling back to polling", error)
        self._watch_polling(state, on_progress, on_image, on_error, image_dir, total)

    def _watch_ws(self, state, pending, on_progress, on_image, on_error, image_dir, total) -> None:
        by_prompt = {state[k]["prompt_id"]: k for k in pending if state[k]["prompt_id"]}
        connection = websocket.create_connection(
            f"{self.ws_url}?clientId={self.client_id}", timeout=self.timeout)
        deadline = time.time() + self.timeout
        try:
            while by_prompt and time.time() < deadline:
                connection.settimeout(min(5.0, max(1.0, deadline - time.time())))
                try:
                    raw = connection.recv()
                except Exception:
                    break
                if not isinstance(raw, str):
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._handle_message(message, state, by_prompt, on_progress, on_image,
                                     on_error, image_dir, total)
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _handle_message(self, message, state, by_prompt, on_progress, on_image, on_error,
                        image_dir, total) -> None:
        kind = message.get("type")
        data = message.get("data") or {}
        prompt_id = data.get("prompt_id")
        key = by_prompt.get(prompt_id)
        if kind == "executed" and key:
            self._store_images(key, data.get("output", {}), state, on_image, image_dir)
            by_prompt.pop(prompt_id, None)
            self._finish(key, state, on_progress, total)
        elif kind == "execution_error" and key:
            detail = data.get("exception_message") or data.get("exception_type") or "execution error"
            state[key]["error"] = str(detail)
            by_prompt.pop(prompt_id, None)
            self._report_error(key, state, on_error)
            self._finish(key, state, on_progress, total)
        elif kind == "executing" and data.get("node") is None and key:
            by_prompt.pop(prompt_id, None)
            self._finish(key, state, on_progress, total)

    def _watch_polling(self, state, on_progress, on_image, on_error, image_dir, total) -> None:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            outstanding = {k: state[k]["prompt_id"] for k in state
                           if not state[k]["done"] and state[k]["prompt_id"]}
            if not outstanding:
                break
            for key, prompt_id in outstanding.items():
                try:
                    entry = self.history(prompt_id)
                except ComfyUIError as error:
                    logger.debug("history poll failed for %s: %s", prompt_id, error)
                    continue
                record = entry.get(prompt_id)
                if not record:
                    continue
                status = (record.get("status") or {}).get("status_str")
                if status == "error":
                    state[key]["error"] = self._error_text(record)
                    self._report_error(key, state, on_error)
                    self._finish(key, state, on_progress, total)
                    continue
                if record.get("outputs"):
                    self._store_images(key, record.get("outputs", {}), state, on_image, image_dir)
                    self._finish(key, state, on_progress, total)
            time.sleep(self.poll_interval)
        for key in state:
            if not state[key]["done"]:
                state[key]["error"] = state[key]["error"] or "timed out waiting for ComfyUI"
                state[key]["done"] = True
                self._report_error(key, state, on_error)

    @staticmethod
    def _error_text(record: dict) -> str:
        for item in (record.get("status") or {}).get("messages", []):
            if isinstance(item, list) and len(item) == 2 and isinstance(item[1], dict):
                message = item[1].get("exception_message") or item[1].get("message")
                if message:
                    return str(message)
        return "ComfyUI reported an execution error"

    def _store_images(self, key, outputs, state, on_image, image_dir) -> None:
        for node_output in (outputs or {}).values():
            for image_info in node_output.get("images", []) or []:
                try:
                    path = self.download_image(image_info, image_dir)
                except ComfyUIError as error:
                    logger.warning("Image download failed for %s: %s", key, error)
                    continue
                state[key]["images"].append(path)
                if on_image:
                    on_image(key, path)

    def _finish(self, key, state, on_progress, total) -> None:
        state[key]["done"] = bool(state[key]["images"]) or bool(state[key]["error"])
        if on_progress:
            on_progress(sum(1 for k in state if state[k]["done"]), total)

    def _report_error(self, key, state, on_error) -> None:
        if on_error:
            on_error(key, state[key].get("error") or "unknown error")

    def close(self) -> None:
        self.session.close()
