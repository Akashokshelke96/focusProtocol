"""Pod-side batch execution for the narrated pipeline.

Runs the whole pipeline on the RunPod pod in phases so heavy models are
loaded once and VRAM is freed between phases:

    SCRIPT -> TTS -> ALIGN -> (free VRAM) -> MANIFEST -> IMAGES -> RENDER -> PACKAGE

The local machine only submits approved scripts and downloads the finals.
"""
