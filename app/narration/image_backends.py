"""Modular image backends for the narration studio.

The default backend is SDXL + IP-Adapter Plus through Diffusers because it
conditions every scene on the canonical character reference images. ComfyUI
remains available for existing RunPod deployments; its text-only workflow is
honest about not doing reference conditioning unless a reference workflow is
configured separately.
"""
from __future__ import annotations

import gc
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from PIL import Image

from app.config.logging_config import get_logger
from app.config.settings import Settings
from app.narration.comfy_client import ComfyUIClient, ComfyUIError

logger = get_logger("narration.images")


class ImageBackendError(RuntimeError):
    """Raised when an image backend cannot generate a valid image."""


@dataclass
class ImageRequest:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    seed: int
    output_path: Path
    reference_images: list[Path] = field(default_factory=list)
    steps: Optional[int] = None
    guidance: Optional[float] = None
    ip_adapter_scale: Optional[float] = None
    label: str = ""


@dataclass
class ImageResult:
    path: Path
    seed: int
    backend: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageBackend(ABC):
    name = "base"

    def __init__(self, settings: Settings,
                 on_log: Optional[Callable[[str], None]] = None):
        self.settings = settings
        self.on_log = on_log or (lambda message: logger.info(message))

    @abstractmethod
    def generate(self, request: ImageRequest) -> ImageResult:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    def identity_similarity(self, image_path: Path,
                            reference_paths: Sequence[str]) -> Optional[float]:
        """Advisory CLIP similarity; backends without an encoder return None."""
        return None

    def close(self) -> None:
        return None


class ComfyUIImageBackend(ImageBackend):
    """ComfyUI HTTP/WebSocket backend for the existing RunPod deployments."""

    name = "comfyui"

    def __init__(self, settings: Settings,
                 on_log: Optional[Callable[[str], None]] = None):
        super().__init__(settings, on_log)
        self._client: Optional[ComfyUIClient] = None

    def _comfy(self) -> ComfyUIClient:
        if self._client is None:
            self._client = ComfyUIClient(self.settings, on_log=self.on_log)
        return self._client

    def health(self) -> dict[str, Any]:
        try:
            stats = self._comfy().health()
            return {"backend": self.name, "reachable": True, "system": stats.get("system", {})}
        except (ComfyUIError, Exception) as error:  # noqa: BLE001 - surfaced as health
            return {"backend": self.name, "reachable": False, "error": str(error)[:300]}

    def generate(self, request: ImageRequest) -> ImageResult:
        client = self._comfy()
        notes: list[str] = []
        if request.reference_images:
            notes.append(
                "ComfyUI workflow is text-only; reference images were not injected. "
                "Use NARRATION_IMAGE_BACKEND=diffusers for identity conditioning.")
            self.on_log(notes[-1])
        workflow, seed = client.build_prompt(
            request.prompt,
            request.negative_prompt,
            request.width,
            request.height,
            seed=request.seed,
            filename_prefix=f"narration_{request.label or 'scene'}",
        )
        results = client.generate_batch({"image": workflow},
                                        image_dir=Path(request.output_path).parent)
        paths = results.get("image") or []
        if not paths:
            raise ImageBackendError("ComfyUI produced no image for this request")
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths[-1], output)
        return ImageResult(
            path=output,
            seed=seed,
            backend=self.name,
            metadata={"notes": notes, "workflow": self.settings.comfy_workflow_path},
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


class DiffusersImageBackend(ImageBackend):
    """SDXL base + IP-Adapter Plus, loaded lazily so unit tests stay light."""

    name = "diffusers"
    _DTYPES = {"float16", "bfloat16", "float32"}

    def __init__(self, settings: Settings,
                 on_log: Optional[Callable[[str], None]] = None):
        super().__init__(settings, on_log)
        self.pipe: Any = None
        self.torch: Any = None
        self.device = "cpu"
        self.dtype_name = settings.narration_image_dtype

    # ------------------------------------------------------------------ setup
    def _hf_token(self) -> Optional[str]:
        token = (self.settings.hf_token or self.settings.hugging_face_hub_token
                 or os.getenv("HUGGING_FACE_HUB_TOKEN", "") or os.getenv("HF_TOKEN", ""))
        return token.strip() or None

    def _load(self) -> None:
        if self.pipe is not None:
            return
        try:
            import torch
            from diffusers import StableDiffusionXLPipeline
        except ImportError as error:  # pragma: no cover - pod/Colab only
            raise ImageBackendError(
                "The Diffusers backend needs torch, diffusers, transformers and accelerate. "
                "Install deploy/requirements-narration-studio.txt."
            ) from error

        self.torch = torch
        requested = (self.settings.narration_image_device or "auto").lower()
        if requested == "auto":
            requested = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = requested
        dtype = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }[self.dtype_name]
        if self.device == "cpu" and dtype == torch.float16:
            dtype = torch.float32
            self.dtype_name = "float32"
        if self.device == "cuda" and not torch.cuda.is_available():
            raise ImageBackendError(
                "NARRATION_IMAGE_DEVICE=cuda but torch cannot see a CUDA GPU")

        self.on_log(f"Loading {self.settings.narration_image_model} on {self.device} ({self.dtype_name})")
        token = self._hf_token()
        kwargs: dict[str, Any] = {
            "torch_dtype": dtype,
            "use_safetensors": True,
            "token": token,
        }
        if dtype == torch.float16:
            kwargs["variant"] = "fp16"
        try:
            pipe = StableDiffusionXLPipeline.from_pretrained(
                self.settings.narration_image_model, **kwargs)
        except Exception:
            # Some mirrors do not publish an fp16 variant.
            kwargs.pop("variant", None)
            kwargs["torch_dtype"] = dtype
            pipe = StableDiffusionXLPipeline.from_pretrained(
                self.settings.narration_image_model, **kwargs)

        if self.settings.narration_image_vae:
            try:
                from diffusers import AutoencoderKL
                vae = AutoencoderKL.from_pretrained(
                    self.settings.narration_image_vae, torch_dtype=dtype, token=token)
                pipe.vae = vae
                self.on_log(f"Using VAE {self.settings.narration_image_vae}")
            except Exception as error:  # noqa: BLE001 - keep the base VAE
                self.on_log(f"Could not load VAE ({error}); using the model's VAE")

        self.on_log(
            f"Loading IP-Adapter {self.settings.narration_ip_adapter_repo}/"
            f"{self.settings.narration_ip_adapter_subfolder}/"
            f"{self.settings.narration_ip_adapter_weight} "
            f"(image encoder: {self.settings.narration_ip_adapter_image_encoder or 'image_encoder'})")
        image_encoder_folder = (
            self.settings.narration_ip_adapter_image_encoder.strip()
            or "image_encoder")
        pipe.load_ip_adapter(
            self.settings.narration_ip_adapter_repo,
            subfolder=self.settings.narration_ip_adapter_subfolder,
            weight_name=self.settings.narration_ip_adapter_weight,
            image_encoder_folder=image_encoder_folder,
        )
        pipe.set_ip_adapter_scale(self.settings.narration_ip_adapter_scale)
        pipe.set_progress_bar_config(disable=True)
        try:
            pipe.enable_vae_slicing()
        except Exception:  # noqa: BLE001 - optional optimisation
            pass

        if self.device == "cuda":
            if self.settings.narration_image_cpu_offload:
                pipe.enable_model_cpu_offload()
                self.on_log("Enabled model CPU offload (low-VRAM safe)")
            else:
                pipe.to("cuda")
        else:
            pipe.to("cpu")
            self.on_log("WARNING: diffusion is running on CPU; expect very slow image generation")
        self.pipe = pipe

    # ----------------------------------------------------------------- public
    def health(self) -> dict[str, Any]:
        try:
            import torch  # noqa: F401
            import diffusers  # noqa: F401
            installed = True
            version = getattr(diffusers, "__version__", "unknown")
            cuda = bool(torch.cuda.is_available())
            device = "cuda" if cuda else "cpu"
            name = torch.cuda.get_device_name(0) if cuda else "CPU"
            vram = (torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)) if cuda else 0
        except ImportError as error:
            return {"backend": self.name, "reachable": False, "error": str(error)}
        return {
            "backend": self.name,
            "reachable": installed,
            "diffusers_version": version,
            "cuda": cuda,
            "device": device,
            "gpu": name,
            "vram_gb": round(vram, 2),
            "model": self.settings.narration_image_model,
            "ip_adapter": self.settings.narration_ip_adapter_weight,
            "loaded": self.pipe is not None,
        }

    def _fit_prompt(self, text: str, max_tokens: int = 75) -> str:
        """Trim to the CLIP budget before diffusers silently truncates it."""
        text = (text or "").strip()
        if not text:
            return text
        fitted = text
        for name in ("tokenizer", "tokenizer_2"):
            tokenizer = getattr(self.pipe, name, None)
            if tokenizer is None:
                continue
            try:
                token_ids = tokenizer(
                    fitted,
                    truncation=True,
                    max_length=max_tokens,
                    add_special_tokens=False,
                ).input_ids
                fitted = tokenizer.decode(token_ids, skip_special_tokens=True).strip()
            except Exception:  # noqa: BLE001 - a backend without a tokenizer is still usable
                return text
        if fitted != text:
            self.on_log(f"Prompt trimmed to the {max_tokens}-token CLIP budget")
        return fitted

    def generate(self, request: ImageRequest) -> ImageResult:
        self._load()
        torch = self.torch
        assert torch is not None and self.pipe is not None
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        generator = torch.Generator(device="cpu").manual_seed(int(request.seed))
        kwargs: dict[str, Any] = {
            "prompt": self._fit_prompt(request.prompt),
            "negative_prompt": (self._fit_prompt(request.negative_prompt)
                                if request.negative_prompt else None),
            "width": int(request.width),
            "height": int(request.height),
            "num_inference_steps": int(request.steps or self.settings.narration_image_steps),
            "guidance_scale": float(request.guidance if request.guidance is not None
                                    else self.settings.narration_image_guidance),
            "generator": generator,
        }
        requested_scale = (request.ip_adapter_scale
                           if request.ip_adapter_scale is not None
                           else self.settings.narration_ip_adapter_scale)

        references = [Path(path) for path in request.reference_images if Path(path).is_file()]
        reference_images: list[Image.Image] = []
        reference_note = ""
        applied_scale = float(requested_scale)
        try:
            for path in references:
                try:
                    reference_images.append(Image.open(path).convert("RGB"))
                except Exception as error:  # noqa: BLE001 - try the remaining references
                    self.on_log(f"Skipping unreadable reference {path}: {error}")

            # Diffusers expects one ip_adapter_image per loaded IP-Adapter.
            # This pipeline loads one adapter, so use the primary full-body
            # reference instead of passing a list that would raise.
            projection_layers = getattr(
                getattr(getattr(self.pipe, "unet", None), "encoder_hid_proj", None),
                "image_projection_layers", None)
            adapter_count = len(projection_layers) if projection_layers is not None else 1
            if reference_images and adapter_count and len(reference_images) > adapter_count:
                reference_note = (
                    f"using {adapter_count} of {len(reference_images)} references "
                    "(one image per IP-Adapter)")
                for extra in reference_images[adapter_count:]:
                    extra.close()
                reference_images = reference_images[:adapter_count]

            if reference_images:
                self.pipe.set_ip_adapter_scale(applied_scale)
                kwargs["ip_adapter_image"] = (
                    reference_images if len(reference_images) > 1 else reference_images[0])
                try:
                    result = self.pipe(**kwargs)
                except Exception as error:  # noqa: BLE001 - older diffusers take one image
                    reference_note = f"multi-reference fallback to first image: {error}"
                    self.on_log(reference_note)
                    kwargs["ip_adapter_image"] = reference_images[0]
                    result = self.pipe(**kwargs)
            else:
                # IP-Adapter changes the UNet to require image_embeds. A text-only
                # call (the first full-body reference, or a scene with no cast)
                # still needs a placeholder; scale 0 keeps it out of the result.
                applied_scale = 0.0
                self.pipe.set_ip_adapter_scale(applied_scale)
                kwargs["ip_adapter_image"] = Image.new("RGB", (224, 224), (127, 127, 127))
                reference_note = "text-only (IP-Adapter scale 0.0)"
                result = self.pipe(**kwargs)

            image = result.images[0]
            image.save(output)
        finally:
            for reference_image in reference_images:
                reference_image.close()

        return ImageResult(
            path=output,
            seed=int(request.seed),
            backend=self.name,
            metadata={
                "model": self.settings.narration_image_model,
                "ip_adapter": self.settings.narration_ip_adapter_weight,
                "ip_adapter_scale": applied_scale,
                "steps": kwargs["num_inference_steps"],
                "guidance": kwargs["guidance_scale"],
                "references": len(reference_images),
                "reference_note": reference_note,
            },
        )

    def identity_similarity(self, image_path: Path,
                            reference_paths: Sequence[str]) -> Optional[float]:
        """CLIP vision cosine similarity, using the IP-Adapter encoder."""
        if not self.settings.narration_identity_check_enabled or not reference_paths:
            return None
        self._load()
        pipe = self.pipe
        encoder = getattr(pipe, "image_encoder", None)
        processor = getattr(pipe, "feature_extractor", None)
        if encoder is None or processor is None:
            return None
        torch = self.torch
        assert torch is not None

        def embed(path: Path):
            with Image.open(path) as image:
                inputs = processor(images=image.convert("RGB"), return_tensors="pt")
            device = next(encoder.parameters()).device
            inputs = {key: value.to(device) for key, value in inputs.items()}
            with torch.no_grad():
                output = encoder(**inputs)
            vector = output.image_embeds
            return vector / vector.norm(dim=-1, keepdim=True)

        scene = embed(Path(image_path))
        best: Optional[float] = None
        for reference in reference_paths:
            path = Path(reference)
            if not path.is_file():
                continue
            similarity = float(torch.matmul(scene, embed(path).T).item())
            best = similarity if best is None else max(best, similarity)
        return best

    def close(self) -> None:
        if self.pipe is not None:
            try:
                self.pipe.to("cpu")
            except Exception:  # noqa: BLE001 - best effort
                pass
            del self.pipe
            self.pipe = None
        gc.collect()
        try:
            if self.torch is not None and self.torch.cuda.is_available():
                self.torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - torch optional
            pass


def build_image_backend(settings: Settings,
                        on_log: Optional[Callable[[str], None]] = None) -> ImageBackend:
    backend = (settings.narration_image_backend or "diffusers").lower()
    if backend == "diffusers":
        return DiffusersImageBackend(settings, on_log=on_log)
    if backend == "comfyui":
        return ComfyUIImageBackend(settings, on_log=on_log)
    raise ImageBackendError(f"Unknown NARRATION_IMAGE_BACKEND: {backend}")
