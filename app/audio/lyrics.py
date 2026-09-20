"""Optional local lyrics transcription for captions. No network services."""
from pathlib import Path
from app.config.logging_config import get_logger

logger = get_logger("audio.lyrics")


def _stamp(seconds, sep):
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{sep}{ms:03}"


def transcribe_lyrics(audio_path, job_dir, model_name="base.en"):
    """Transcribe sung speech from the final mix into SRT+VTT sidecars.

    Returns (srt_path, segment_count) or (None, 0) when nothing singable is
    found. Never raises for empty results; raises only on real failures.
    """
    from faster_whisper import WhisperModel
    job_dir = Path(job_dir)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_path), vad_filter=True)
    kept = [(s.start, s.end, s.text.strip()) for s in segments if s.text and s.text.strip()]
    if not kept:
        logger.info("No lyrics detected; skipping captions")
        return None, 0
    srt_path = job_dir / "lyrics.srt"
    vtt_path = job_dir / "lyrics.vtt"
    with srt_path.open("w", encoding="utf-8") as stream:
        for index, (start, end, text) in enumerate(kept, 1):
            stream.write(f"{index}\n{_stamp(start, ',')} --> {_stamp(end, ',')}\n{text}\n\n")
    with vtt_path.open("w", encoding="utf-8") as stream:
        stream.write("WEBVTT\n\n")
        for start, end, text in kept:
            stream.write(f"{_stamp(start, '.')} --> {_stamp(end, '.')}\n{text}\n\n")
    logger.info("Lyrics captions: %s segments -> %s", len(kept), srt_path)
    return srt_path, len(kept)
