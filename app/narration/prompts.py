"""LLM prompt templates for the narrated pipeline."""

NARRATION_SCRIPT_PROMPT = """You are a professional documentary scriptwriter for the YouTube channel "{channel}".

Write a complete, narration-only spoken script for a {duration_minutes}-minute video about:
{topic}

Hard requirements:
- Target about {word_target} spoken words (roughly 150 words per minute). Stay between {word_min} and {word_max} words.
- Open with a strong 10-15 second hook that poses the central question of the video.
- Follow a clear narrative arc: hook, context, evidence and concrete examples, a surprising turn, then a satisfying payoff.
- Keep a single consistent narrative voice and a documentary tone.
- Do NOT include scene directions, camera notes, timestamps, speaker labels, chapter titles, markdown, emojis, or bullet lists.
- Output plain continuous prose only, because the text is sent directly to a text-to-speech engine.

Return ONLY a JSON object with this exact shape:
{{"title": "short YouTube title", "hook": "the opening hook sentence", "script": "the full narration text"}}
"""

NARRATION_MANIFEST_BATCH_PROMPT = """You are a film director's assistant building a shot list for an animated documentary.

Universal visual style for EVERY shot (already applied automatically, do not repeat it):
{style_prefix}

Below is a JSON array of narration beats. Each beat has an index, its narration text, and its on-screen duration in seconds.
For EACH beat, write exactly one vivid, concrete visual description that literally depicts what is being narrated at that moment.

Rules:
- Describe a single cinematic still image: subject, action, setting, mood, lighting, camera framing.
- 18 to 40 words per prompt. Concrete nouns, no abstractions.
- Maintain visual continuity across beats: recurring characters, settings and lighting should evolve naturally, not jump randomly.
- Do NOT add the universal style, resolution, aspect ratio, or "no text" notes.
- No text, captions, logos or watermarks may appear in any image.
- Return one prompt per input beat, in the same order.

Beats:
{beats}

Return ONLY a JSON array shaped like:
[{{"index": 1, "prompt": "..."}}, {{"index": 2, "prompt": "..."}}]
"""

NARRATION_THUMBNAIL_PROMPT = """Design one high-CTR YouTube thumbnail image concept for the video below.

Title: {title}
Topic: {topic}
Universal visual style: {style_prefix}

Return ONLY a JSON object with this exact shape:
{{"prompt": "one cinematic, emotionally striking thumbnail image description, 20-45 words, single dominant subject, high contrast, no text or logos"}}
"""

NARRATION_METADATA_PROMPT = """Write YouTube metadata for a narrated documentary video.

Topic: {topic}
Title: {title}
Script excerpt:
{script_excerpt}

Return ONLY a JSON object with this exact shape:
{{"title": "optimized title under 70 chars", "description": "2-4 paragraph description with a hook and a soft call to subscribe", "tags": ["tag1", "tag2", "tag3"]}}
"""
