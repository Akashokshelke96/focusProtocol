"""Optional, seeded image-layer transforms; no audio or overlay processing."""
import math
import random
import secrets
from typing import Literal
from pydantic import BaseModel, Field


class ImageMotion(BaseModel):
    enabled: bool = False
    preset: Literal['static', 'gentle_float', 'slow_sway', 'slow_drift', 'gentle_zoom', 'float_zoom', 'cinematic', 'random_gentle'] = 'gentle_float'
    strength: Literal['low', 'medium'] = 'low'
    speed: Literal['slow', 'very_slow'] = 'slow'
    rotation: bool = False
    zoom: bool = False
    randomize: bool = True
    seed: int | None = Field(default=None, ge=0, le=2147483647)


def configuration(value=None):
    motion = ImageMotion.model_validate(value or {})
    if motion.enabled and motion.seed is None:
        motion.seed = secrets.randbelow(2147483648) if motion.randomize else 0
    return motion.model_dump()


def parameters(config):
    """All oscillations complete integer cycles in the existing 60s motion clip."""
    m = ImageMotion.model_validate(config)
    rng = random.Random(m.seed or 0)
    phase = rng.uniform(0, 2 * math.pi) if m.randomize else 0
    preset = rng.choice(['gentle_float', 'slow_sway', 'slow_drift', 'float_zoom']) if m.preset == 'random_gentle' else m.preset
    amount = .003 if m.strength == 'low' else .006
    x = amount if preset not in ('static', 'gentle_zoom') else 0
    y = amount * .65 if preset in ('gentle_float', 'slow_drift', 'float_zoom', 'cinematic') else 0
    zoom = (.006 if m.strength == 'low' else .01) if m.zoom or preset in ('gentle_zoom', 'float_zoom', 'cinematic') else 0
    angle = math.radians(.15 if m.strength == 'low' else .3) if m.rotation or preset == 'cinematic' else 0
    return dict(x=x, y=y, zoom=zoom, angle=angle, phase=phase,
                y_phase=phase if preset == 'slow_drift' else phase + math.pi / 2,
                period=60 if m.speed == 'very_slow' else 30)


def transform_filter(config, fps):
    """One subpixel affine resampling pass, after crop-to-fill, before overlays.

    Four destination corners implement translation/scale/rotation together.
    Fixed 4% overscan exceeds the bounded translations and rotation; scale
    breathing only adds headroom. Expressions depend on frame time, not audio.
    """
    p = parameters(config)
    phase = f"(2*PI*on/({fps}*{p['period']})+{p['phase']:.12f})"
    yphase = f"(2*PI*on/({fps}*{p['period']})+{p['y_phase']:.12f})"
    scale = f"(1.04+{p['zoom']}*(1-cos({phase})))"
    angle = f"({p['angle']}*sin({phase}))"
    tx, ty = f"W*{p['x']}*sin({phase})", f"H*{p['y']}*sin({yphase})"
    coords = []
    for i, (x, y) in enumerate([('-W/2', '-H/2'), ('W/2', '-H/2'), ('-W/2', 'H/2'), ('W/2', 'H/2')]):
        coords.extend([f"x{i}='W/2+{tx}+{scale}*(({x})*cos({angle})-({y})*sin({angle}))'",
                       f"y{i}='H/2+{ty}+{scale}*(({x})*sin({angle})+({y})*cos({angle}))'"])
    return 'perspective=' + ':'.join(coords) + ':sense=destination:eval=frame:interpolation=linear'
