"""Narration audio: remote Kokoro, local Kokoro/Piper TTS, and WhisperX alignment.

Remote services are expected to expose:
- TTS: an OpenAI-compatible ``/v1/audio/speech`` endpoint (e.g. Kokoro-FastAPI).
- Alignment: a WhisperX HTTP endpoint that accepts an audio upload and
  returns ``segments`` with start/end (and optionally word) timings.

Local backends (``kokoro_local``, ``piper_local``, ``whisperx_local``) let a
Colab T4 or a RunPod worker run without a second service. When alignment is
unavailable the engine falls back to a deterministic proportional estimate.
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any, Optional

import requests

from app.config.logging_config import get_logger
from app.config.settings import Settings
from app.narration.models import AlignSegment, AlignmentResult, WordTiming
from app.narration.text import clean, split_sentences, word_count

logger = get_logger("narration.audio")


class RemoteServiceError(RuntimeError):
    """Raised when a required remote audio service fails."""


def _speech_endpoint(base: str) -> str:
    base = (base or "").rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1/audio/speech"):
        return base
    if base.endswith("/v1"):
        return base + "/audio/speech"
    return base + "/v1/audio/speech"


class AudioEngine:
    """Generates narration audio and word/sentence timing."""

    def __init__(self, settings: Settings, work_dir: Path):
        self.settings = settings
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # Cached in-process models (kokoro_local / whisperx_local backends).
        self._kokoro = None
        self._whisperx = None
        self._whisperx_align = None

    # ------------------------------------------------------------------ TTS
    def synthesize(self, script_text: str, output_path: Path) -> Path:
        """Generate narration audio for the script via the remote TTS service."""
        text = clean(script_text)
        if not text:
            raise ValueError("Cannot synthesize empty narration text")
        if self.settings.narration_tts_backend == "kokoro_local":
            return self._synthesize_kokoro(text, Path(output_path))
        if self.settings.narration_tts_backend == "piper_local":
            return self._synthesize_piper(text, Path(output_path))
        endpoint = _speech_endpoint(self.settings.narration_tts_url)
        if not endpoint:
            raise RemoteServiceError("NARRATION_TTS_URL is not configured")

        headers = {"Content-Type": "application/json"}
        if self.settings.narration_tts_api_key:
            headers["Authorization"] = f"Bearer {self.settings.narration_tts_api_key}"
        payload = {
            "model": self.settings.narration_tts_model,
            "input": text,
            "voice": self.settings.narration_tts_voice,
            "response_format": self.settings.narration_tts_format,
            "speed": self.settings.narration_tts_speed,
        }

        output_path = Path(output_path)
        try:
            response = requests.post(
                endpoint, headers=headers, json=payload,
                timeout=self.settings.narration_tts_timeout_seconds,
            )
            if response.status_code >= 400 and self.settings.narration_tts_format == "wav":
                logger.warning("TTS rejected the full script (%s); retrying in chunks", response.status_code)
                self._synthesize_chunked(text, output_path, headers, endpoint)
            else:
                response.raise_for_status()
                output_path.write_bytes(response.content)
        except requests.RequestException as error:
            raise RemoteServiceError(f"TTS request failed: {error}") from error

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RemoteServiceError("TTS returned no audio data")
        logger.info("Narration audio written: %s (%.1f KB)", output_path.name, output_path.stat().st_size / 1024)
        return output_path

    def _synthesize_chunked(self, text: str, output_path: Path, headers: dict, endpoint: str) -> None:
        """Fallback for long scripts: synthesize sentence chunks and stitch WAVs."""
        sentences = split_sentences(text) or [text]
        chunks, buffer = [], []
        for sentence in sentences:
            buffer.append(sentence)
            if word_count(" ".join(buffer)) >= 350:
                chunks.append(" ".join(buffer))
                buffer = []
        if buffer:
            chunks.append(" ".join(buffer))

        part_paths = []
        for index, chunk in enumerate(chunks):
            body = dict(model=self.settings.narration_tts_model, input=chunk,
                        voice=self.settings.narration_tts_voice,
                        response_format=self.settings.narration_tts_format,
                        speed=self.settings.narration_tts_speed)
            response = requests.post(endpoint, headers=headers, json=body,
                                     timeout=self.settings.narration_tts_timeout_seconds)
            response.raise_for_status()
            part = self.work_dir / f"narration_part_{index:03d}.wav"
            part.write_bytes(response.content)
            part_paths.append(part)
        self._concat_wavs(part_paths, output_path)
        for part in part_paths:
            part.unlink(missing_ok=True)

    @staticmethod
    def _concat_wavs(paths: list[Path], output_path: Path) -> None:
        with wave.open(str(paths[0]), "rb") as first:
            params = first.getparams()
        with wave.open(str(output_path), "wb") as writer:
            writer.setparams(params)
            for path in paths:
                with wave.open(str(path), "rb") as reader:
                    writer.writeframes(reader.readframes(reader.getnframes()))

    # ------------------------------------------------------------- alignment
    def align(self, audio_path: Path) -> Optional[AlignmentResult]:
        """Return word/sentence timings from WhisperX, or None if unavailable."""
        if self.settings.narration_align_backend == "whisperx_local":
            try:
                return self._align_whisperx(Path(audio_path))
            except Exception as error:  # noqa: BLE001 - degrade to estimate
                logger.warning("Local WhisperX alignment failed; falling back to estimate: %s", error)
                return None
        if not self.settings.narration_align_url:
            logger.warning("NARRATION_ALIGN_URL not configured; alignment will be estimated")
            return None
        headers = {}
        if self.settings.narration_align_token:
            headers["Authorization"] = f"Bearer {self.settings.narration_align_token}"
        try:
            with open(audio_path, "rb") as audio_file:
                response = requests.post(
                    self.settings.narration_align_url,
                    headers=headers,
                    files={"file": (Path(audio_path).name, audio_file, "audio/wav")},
                    timeout=self.settings.narration_align_timeout_seconds,
                )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, json.JSONDecodeError) as error:
            logger.warning("WhisperX alignment failed; falling back to estimate: %s", error)
            return None

        result = _parse_alignment(payload)
        if not result.segments:
            logger.warning("WhisperX returned no segments; falling back to estimate")
            return None
        logger.info("Alignment received: %s segments from WhisperX", len(result.segments))
        return result

    # ---------------------------------------------------- local model backends
    def _synthesize_kokoro(self, text: str, output_path: Path) -> Path:
        """In-process Kokoro TTS; the model stays resident until unload_models()."""
        try:
            import numpy as np
            import soundfile as sf
        except ImportError as error:  # pragma: no cover - pod-only deps
            raise RemoteServiceError(
                "kokoro_local backend needs the 'kokoro' and 'soundfile' packages installed") from error

        pipeline = self._kokoro_pipeline()
        pieces = []
        for _graphemes, _phonemes, audio in pipeline(
                text, voice=self.settings.narration_tts_voice, speed=self.settings.narration_tts_speed):
            if audio is None:
                continue
            pieces.append(audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio))
        if not pieces:
            raise RemoteServiceError("Kokoro produced no audio samples")
        samples = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), samples, self.settings.narration_kokoro_sample_rate)
        logger.info("Kokoro narration written: %s", output_path.name)
        return output_path

    def _synthesize_piper(self, text: str, output_path: Path) -> Path:
        """Local Piper TTS, invoked as a CLI so Colab needs no Python glue."""
        model = (self.settings.narration_piper_model or "").strip()
        if not model or not Path(model).is_file():
            raise RemoteServiceError(
                "piper_local needs NARRATION_PIPER_MODEL pointing at a downloaded .onnx voice")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        binary = shutil.which(self.settings.narration_piper_binary or "piper")
        if binary:
            command = [binary]
        else:
            command = [sys.executable, "-m", "piper"]
        command += ["--model", model, "--output_file", str(output_path)]
        config = (self.settings.narration_piper_config or "").strip()
        if config:
            command += ["--config", config]
        if self.settings.narration_piper_speaker:
            command += ["--speaker", str(self.settings.narration_piper_speaker)]
        scale = float(getattr(self.settings, "narration_piper_length_scale", 1.0) or 1.0)
        if abs(scale - 1.0) > 0.001:
            command += ["--length-scale", f"{scale:g}"]
        try:
            result = subprocess.run(
                command, input=text, text=True, capture_output=True,
                timeout=max(120, int(self.settings.narration_tts_timeout_seconds)))
        except (OSError, subprocess.SubprocessError) as error:
            raise RemoteServiceError(f"Piper TTS failed to start: {error}") from error
        if result.returncode != 0:
            raise RemoteServiceError(
                f"Piper TTS failed ({result.returncode}): {result.stderr[-800:]}")
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RemoteServiceError("Piper produced no audio data")
        logger.info("Piper narration written: %s (%.1f KB)",
                    output_path.name, output_path.stat().st_size / 1024)
        return output_path

    def _kokoro_pipeline(self):
        if self._kokoro is None:
            try:
                from kokoro import KPipeline
            except ImportError as error:  # pragma: no cover - pod-only dep
                raise RemoteServiceError("kokoro package is not installed") from error
            logger.info("Loading Kokoro TTS pipeline (lang=%s)", self.settings.narration_kokoro_lang)
            self._kokoro = KPipeline(lang_code=self.settings.narration_kokoro_lang)
        return self._kokoro

    def _align_whisperx(self, audio_path: Path) -> AlignmentResult:
        """In-process WhisperX alignment with word-level timestamps."""
        try:
            import whisperx
        except ImportError as error:  # pragma: no cover - pod-only dep
            raise RemoteServiceError("whisperx package is not installed") from error

        device = self.settings.narration_whisperx_device
        audio = whisperx.load_audio(str(audio_path))
        if self._whisperx is None:
            logger.info("Loading WhisperX model=%s device=%s",
                        self.settings.narration_whisperx_model, device)
            self._whisperx = whisperx.load_model(
                self.settings.narration_whisperx_model, device,
                compute_type=self.settings.narration_whisperx_compute_type)
        result = self._whisperx.transcribe(audio, batch_size=16)
        if not result.get("segments"):
            return None
        if self._whisperx_align is None:
            self._whisperx_align = self._load_align_model(result.get("language", "en"), device)
        align_model, metadata = self._whisperx_align
        aligned = whisperx.align(result["segments"], align_model, metadata, audio, device,
                                 return_char_alignments=False)
        parsed = _parse_alignment(aligned)
        if not parsed.segments:
            return None
        parsed.source = "whisperx"
        logger.info("Local WhisperX alignment: %s segments", len(parsed.segments))
        return parsed

    @staticmethod
    def _load_align_model(language: str, device: str):
        import whisperx
        logger.info("Loading WhisperX alignment model (%s)", language)
        return whisperx.load_align_model(language_code=language, device=device)

    def unload_models(self) -> bool:
        """Release Kokoro + WhisperX from VRAM so the image model can load."""
        released = self._kokoro is not None or self._whisperx is not None
        self._kokoro = None
        self._whisperx = None
        self._whisperx_align = None
        if released:
            import gc
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:  # pragma: no cover - torch optional
                pass
            logger.info("Released Kokoro/WhisperX models from memory")
        return released

    def estimate_alignment(self, script_text: str, duration_seconds: float) -> AlignmentResult:
        """Deterministic proportional timings when WhisperX is unavailable."""
        sentences = split_sentences(script_text) or [clean(script_text)]
        total_words = max(1, sum(word_count(s) for s in sentences))
        segments: list[AlignSegment] = []
        cursor = 0.0
        for sentence in sentences:
            share = word_count(sentence) / total_words
            span = share * max(0.0, duration_seconds)
            segments.append(AlignSegment(start=round(cursor, 3), end=round(cursor + span, 3), text=sentence))
            cursor += span
        if segments:
            segments[-1].end = round(max(segments[-1].end, duration_seconds), 3)
        logger.info("Estimated alignment: %s sentence segments", len(segments))
        return AlignmentResult(segments=segments, duration_seconds=duration_seconds, source="estimated")


def _parse_alignment(payload: Any) -> AlignmentResult:
    """Tolerantly parse a variety of WhisperX HTTP response shapes."""
    if isinstance(payload, dict):
        for key in ("result", "data", "output"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                payload = nested
                break
    segments_raw = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(segments_raw, list):
        return AlignmentResult()

    segments: list[AlignSegment] = []
    duration = 0.0
    for item in segments_raw:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start))
        except (TypeError, ValueError):
            continue
        words: list[WordTiming] = []
        for word in item.get("words") or []:
            if not isinstance(word, dict):
                continue
            try:
                words.append(WordTiming(
                    word=str(word.get("word", word.get("text", ""))).strip(),
                    start=float(word.get("start", start)),
                    end=float(word.get("end", end)),
                    score=float(word.get("score", word.get("probability", 0.0)) or 0.0),
                ))
            except (TypeError, ValueError):
                continue
        segments.append(AlignSegment(start=start, end=end, text=str(item.get("text", "")).strip(), words=words))
        duration = max(duration, end)

    language = str(payload.get("language", "")) if isinstance(payload, dict) else ""
    return AlignmentResult(segments=segments, language=language, duration_seconds=duration, source="whisperx")
