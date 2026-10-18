"""Narrated long-form video pipeline (sibling to the jazz pipeline).

Turns a topic into a 10-11 minute narrated video: OpenRouter script ->
local approval -> remote RunPod TTS + WhisperX alignment + ComfyUI image
generation -> FFmpeg assembly. Reuses the shared Settings, JobManager,
GeminiProvider, FFmpeg utilities and Flask app.
"""
