"""Reference images, scene images, retries, quality gates, and resume cache."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from app.config.logging_config import get_logger
from app.config.settings import Settings
from app.narration.character_bible import CharacterBibleBuilder
from app.narration.image_backends import ImageBackend, ImageBackendError, ImageRequest
from app.narration.models import (
    CharacterBible,
    CharacterReference,
    Scene,
    SceneManifest,
)
from app.narration.quality import QualityChecker
from app.narration.scene_manifest import compose_positive
from app.narration.seeding import stable_seed

logger = get_logger("narration.imagegen")


class ImageGenerationError(RuntimeError):
    """Raised when one or more scenes cannot be generated to a usable standard."""


@dataclass
class GenerationStats:
    total: int = 0
    generated: int = 0
    cached: int = 0
    failed: int = 0
    needs_review: int = 0
    references: int = 0
    flags: dict[str, int] = field(default_factory=dict)

    def note_flags(self, flags: list[str]) -> None:
        for flag in flags:
            key = flag.split(":", 1)[0]
            self.flags[key] = self.flags.get(key, 0) + 1

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "generated": self.generated,
            "cached": self.cached,
            "failed": self.failed,
            "needs_review": self.needs_review,
            "references": self.references,
            "flags": dict(sorted(self.flags.items())),
        }


def _digest_bytes(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


class ImageGenerationService:
    """Generates canonical references first, then every scene with that lock."""

    def __init__(
        self,
        settings: Settings,
        backend: ImageBackend,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ):
        self.settings = settings
        self.backend = backend
        self.on_log = on_log or (lambda message: logger.info(message))
        self.on_progress = on_progress
        self.quality = QualityChecker(settings)
        self._reference_digests: dict[str, str] = {}

    # ------------------------------------------------------------- references
    def ensure_references(self, bible: CharacterBible, job_dir: Path,
                          on_save: Optional[Callable[[CharacterBible], None]] = None) -> GenerationStats:
        stats = GenerationStats()
        characters_dir = Path(job_dir) / "characters"
        characters_dir.mkdir(parents=True, exist_ok=True)
        views = [view.strip() for view in (self.settings.narration_reference_views or "").split(",")
                 if view.strip()]
        if not views:
            views = ["full_body", "portrait"]

        for character in bible.characters:
            for view in views:
                stats.total += 1
                prompt = (character.reference_prompt if view == "full_body"
                          else character.portrait_prompt) or character.reference_prompt
                if not prompt:
                    prompt = (f"Character reference of {character.name}. {character.anchor()} "
                              "Full figure, neutral warm grey backdrop, soft even light.")
                seed = stable_seed(
                    int(character.seed or self.settings.narration_seed),
                    "reference", character.id, view, prompt)
                # Later views are conditioned on the first full-body reference.
                reference_paths: list[Path] = []
                if view != "full_body":
                    primary = next(
                        (Path(ref.path) for ref in character.references
                         if ref.view == "full_body" and Path(ref.path).is_file()), None)
                    if primary is not None:
                        reference_paths = [primary]
                key = self._key(
                    prompt=prompt,
                    negative=self.settings.narration_negative_prompt,
                    seed=seed,
                    width=self.settings.narration_reference_width,
                    height=self.settings.narration_reference_height,
                    references=reference_paths,
                    model=f"{self.backend.name}:{self.settings.narration_image_model}",
                )
                output = characters_dir / character.id / f"reference_{view}_{key}.png"
                existing = next(
                    (reference for reference in character.references
                     if reference.view == view and reference.seed == seed
                     and key in Path(reference.path).name
                     and Path(reference.path).is_file()
                     and self.quality.inspect(Path(reference.path), 512, 512).ok),
                    None)
                if existing is not None:
                    stats.cached += 1
                    continue

                generated = self._generate_reference(
                    character_id=character.id,
                    prompt=compose_positive(
                        bible.style_lock or self.settings.narration_style_prefix,
                        prompt,
                        character.anchor()),
                    seed=seed,
                    output=output,
                    reference_paths=reference_paths,
                )
                if generated is None:
                    raise ImageGenerationError(
                        f"Could not generate a usable {view} reference for {character.name}")
                character.references = [
                    reference for reference in character.references
                    if not (reference.view == view and reference.seed == seed)
                ]
                character.references.append(CharacterReference(
                    view=view,
                    path=str(generated.resolve()),
                    prompt=prompt,
                    seed=seed,
                    width=self.settings.narration_reference_width,
                    height=self.settings.narration_reference_height,
                ))
                stats.generated += 1
                stats.references += 1
                if on_save:
                    on_save(bible)
        self.on_log(
            f"Character references ready: {stats.references} generated, {stats.cached} cached")
        return stats

    def _generate_reference(self, character_id: str, prompt: str, seed: int, output: Path,
                            reference_paths: list[Path]) -> Optional[Path]:
        attempts = max(1, self.settings.narration_max_retries + 1)
        for attempt in range(attempts):
            candidate = output.with_name(output.stem + f"_try{attempt + 1}.png")
            try:
                self.backend.generate(ImageRequest(
                    prompt=prompt,
                    negative_prompt=self.settings.narration_negative_prompt,
                    width=self.settings.narration_reference_width,
                    height=self.settings.narration_reference_height,
                    seed=seed + attempt * 7919,
                    output_path=candidate,
                    reference_images=reference_paths,
                    steps=self.settings.narration_reference_steps,
                    label=f"ref_{character_id}",
                ))
                quality = self.quality.inspect(candidate, 512, 512)
                if quality.ok:
                    candidate.replace(output)
                    return output
                self.on_log(
                    f"Reference {character_id} attempt {attempt + 1} rejected: "
                    f"{', '.join(quality.flags)}")
            except ImageBackendError as error:
                self.on_log(f"Reference {character_id} attempt {attempt + 1} failed: {error}")
            finally:
                candidate.unlink(missing_ok=True)
        return None

    # ------------------------------------------------------------------ scenes
    def generate_manifest(
        self,
        manifest: SceneManifest,
        image_dir: Path,
        on_save: Optional[Callable[[SceneManifest], None]] = None,
    ) -> GenerationStats:
        image_dir = Path(image_dir)
        image_dir.mkdir(parents=True, exist_ok=True)
        stats = GenerationStats(total=len(manifest.scenes))
        bible = manifest.character_bible
        previous_hashes: list[tuple[int, int]] = []

        for position, scene in enumerate(manifest.scenes):
            identity = manifest.identity_for(scene.character_ids)
            negative = scene.negative_prompt or manifest.negative_prompt
            prompt = compose_positive(manifest.style_prefix, scene.prompt, identity)
            references = [Path(path) for path in manifest.references_for(scene.character_ids)
                          if Path(path).is_file()]
            base_seed = scene.seed if scene.seed is not None else stable_seed(
                self.settings.narration_seed, "scene", scene.index, prompt)
            key = self._key(
                prompt=prompt,
                negative=negative,
                seed=base_seed,
                width=self.settings.narration_image_width,
                height=self.settings.narration_image_height,
                references=references,
                model=f"{self.backend.name}:{self.settings.narration_image_model}",
            )
            expected = image_dir / f"scene_{scene.index:04d}_{key}.png"
            cached_path = expected
            if not cached_path.is_file() and scene.image_path and scene.cache_key == key:
                old = Path(scene.image_path)
                if old.is_file():
                    cached_path = old
            if cached_path.is_file():
                quality = self.quality.check_scene(
                    cached_path, scene.character_ids,
                    [str(path) for path in references],
                    identity_scorer=self.backend.identity_similarity,
                    previous_hashes=previous_hashes,
                )
                if quality.ok:
                    scene.image_path = str(cached_path.resolve())
                    scene.cache_key = key
                    scene.seed = int(scene.seed if scene.seed is not None else base_seed)
                    scene.backend = self.backend.name
                    scene.quality_flags = quality.flags
                    scene.validation_status = "needs_review" if quality.soft_flags else "passed"
                    scene.attempts = max(1, scene.attempts)
                    previous_hashes.append((scene.index, quality.dhash))
                    stats.cached += 1
                    if quality.soft_flags:
                        stats.needs_review += 1
                        stats.note_flags(quality.soft_flags)
                    if on_save:
                        on_save(manifest)
                    self._progress(position + 1, len(manifest.scenes))
                    continue
                cached_path.unlink(missing_ok=True)

            scene.image_path = None
            scene.validation_status = "pending"
            scene.quality_flags = []
            success = False
            last_flags: list[str] = []
            attempts = max(1, self.settings.narration_max_retries + 1)
            for attempt in range(attempts):
                seed = base_seed + attempt * 7919
                candidate = image_dir / f"scene_{scene.index:04d}_{key}_try{attempt + 1}.png"
                scale = self.settings.narration_ip_adapter_scale
                if attempt and last_flags and last_flags[0].startswith("identity_low"):
                    scale = min(1.5, scale + self.settings.narration_identity_retry_scale_boost)
                try:
                    result = self.backend.generate(ImageRequest(
                        prompt=prompt,
                        negative_prompt=negative,
                        width=self.settings.narration_image_width,
                        height=self.settings.narration_image_height,
                        seed=seed,
                        output_path=candidate,
                        reference_images=references,
                        ip_adapter_scale=scale,
                        label=f"scene_{scene.index:04d}",
                    ))
                except ImageBackendError as error:
                    last_flags = [f"backend_error:{error}"]
                    self.on_log(f"Scene {scene.index} attempt {attempt + 1} failed: {error}")
                    candidate.unlink(missing_ok=True)
                    continue

                quality = self.quality.check_scene(
                    candidate, scene.character_ids,
                    [str(path) for path in references],
                    identity_scorer=self.backend.identity_similarity,
                    previous_hashes=previous_hashes,
                )
                last_flags = quality.flags
                if quality.ok:
                    retry_soft = any(
                        flag.startswith(("identity_low", "duplicate_of"))
                        for flag in quality.soft_flags)
                    if retry_soft and attempt + 1 < attempts:
                        self.on_log(
                            f"Scene {scene.index} attempt {attempt + 1} flagged "
                            f"{', '.join(quality.soft_flags)}; retrying")
                        candidate.unlink(missing_ok=True)
                        continue
                    candidate.replace(expected)
                    scene.image_path = str(expected.resolve())
                    scene.cache_key = key
                    scene.seed = int(result.seed)
                    scene.backend = result.backend
                    scene.attempts = scene.attempts + attempt + 1
                    scene.quality_flags = quality.flags
                    scene.validation_status = "needs_review" if quality.soft_flags else "passed"
                    previous_hashes.append((scene.index, quality.dhash))
                    success = True
                    stats.generated += 1
                    if quality.soft_flags:
                        stats.needs_review += 1
                        stats.note_flags(quality.soft_flags)
                    break
                self.on_log(
                    f"Scene {scene.index} attempt {attempt + 1} rejected: "
                    f"{', '.join(quality.flags)}")
                candidate.unlink(missing_ok=True)

            if not success:
                scene.image_path = None
                scene.validation_status = "failed"
                scene.quality_flags = last_flags
                scene.attempts = scene.attempts + attempts
                scene.backend = self.backend.name
                stats.failed += 1
                stats.note_flags(last_flags)
                self.on_log(f"Scene {scene.index} failed after {attempts} attempts")
            if on_save:
                on_save(manifest)
            self._progress(position + 1, len(manifest.scenes))

        report = stats.as_dict()
        _atomic_json(image_dir / "generation_report.json", report)
        self.on_log(
            f"Scene images complete: {stats.generated} generated, {stats.cached} cached, "
            f"{stats.failed} failed, {stats.needs_review} need review")
        if stats.failed:
            raise ImageGenerationError(
                f"{stats.failed} of {stats.total} scene images failed quality/generation checks. "
                "Partial results were saved; fix the backend and resume the same job.")
        return stats

    # --------------------------------------------------------------- thumbnail
    def generate_thumbnail(self, manifest: SceneManifest, thumbnail_dir: Path) -> Optional[Path]:
        thumbnail_dir = Path(thumbnail_dir)
        thumbnail_dir.mkdir(parents=True, exist_ok=True)
        identity = manifest.identity_for(manifest.thumbnail_character_ids or None)
        prompt = compose_positive(manifest.style_prefix, manifest.thumbnail_prompt, identity)
        seed = stable_seed(
            self.settings.narration_seed, "thumbnail", manifest.title, manifest.topic, prompt)
        references = [Path(path) for path in manifest.references_for(
            manifest.thumbnail_character_ids or None) if Path(path).is_file()]
        key = self._key(
            prompt=prompt,
            negative=manifest.negative_prompt,
            seed=seed,
            width=self.settings.narration_thumbnail_width,
            height=self.settings.narration_thumbnail_height,
            references=references,
            model=f"{self.backend.name}:{self.settings.narration_image_model}",
        )
        output = thumbnail_dir / f"thumbnail_source_{key}.png"
        if output.is_file():
            quality = self.quality.inspect(
                output, min(640, self.settings.narration_thumbnail_width // 2),
                min(360, self.settings.narration_thumbnail_height // 2))
            if quality.ok:
                return output
            output.unlink(missing_ok=True)

        attempts = max(1, self.settings.narration_max_retries + 1)
        for attempt in range(attempts):
            candidate = thumbnail_dir / f"thumbnail_source_{key}_try{attempt + 1}.png"
            try:
                self.backend.generate(ImageRequest(
                    prompt=prompt,
                    negative_prompt=manifest.negative_prompt,
                    width=self.settings.narration_thumbnail_width,
                    height=self.settings.narration_thumbnail_height,
                    seed=seed + attempt * 7919,
                    output_path=candidate,
                    reference_images=references,
                    label="thumbnail",
                ))
                if self.quality.inspect(candidate, 640, 360).ok:
                    candidate.replace(output)
                    manifest.thumbnail_source = str(output.resolve())
                    return output
            except ImageBackendError as error:
                self.on_log(f"Thumbnail attempt {attempt + 1} failed: {error}")
            finally:
                candidate.unlink(missing_ok=True)
        self.on_log("Thumbnail image generation failed after retries")
        return None

    # ---------------------------------------------------------------- helpers
    def _progress(self, done: int, total: int) -> None:
        if self.on_progress:
            try:
                self.on_progress(done, total)
            except Exception:  # noqa: BLE001 - progress is best effort
                pass

    def _key(self, prompt: str, negative: str, seed: int, width: int, height: int,
             references: list[Path], model: str) -> str:
        digest = hashlib.sha256()
        digest.update(f"{model}|{width}x{height}|{seed}".encode("utf-8"))
        digest.update(b"\0")
        digest.update((prompt or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update((negative or "").encode("utf-8"))
        for reference in references:
            digest.update(b"\0")
            digest.update(self._reference_digest(Path(reference)).encode("ascii"))
        return digest.hexdigest()[:12]

    def _reference_digest(self, path: Path) -> str:
        key = str(path.resolve())
        if key not in self._reference_digests:
            self._reference_digests[key] = _digest_bytes(path) if path.is_file() else "missing"
        return self._reference_digests[key]
