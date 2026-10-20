"""LLM prompt templates for the narrated pipeline."""

NARRATION_SCRIPT_PROMPT = """You are a professional documentary scriptwriter for the YouTube channel "{channel}".

Write a complete, narration-only spoken script for a {duration_minutes}-minute video about:
{topic}

Hard requirements:
- Target about {word_target} spoken words (roughly 150 words per minute). Stay between {word_min} and {word_max} words.
- Open with a strong 10-15 second hook that poses the central question of the video.
- Follow a clear narrative arc: hook, context, evidence and concrete examples, a surprising turn, then a satisfying payoff.
- Keep a single consistent narrative voice and a friendly, engaging explainer tone (this is a stickman explainer video).
- Do NOT include scene directions, camera notes, timestamps, speaker labels, chapter titles, markdown, emojis, or bullet lists.
- Output plain continuous prose only, because the text is sent directly to a text-to-speech engine.

Return ONLY a JSON object with this exact shape:
{{"title": "short YouTube title", "hook": "the opening hook sentence", "script": "the full narration text"}}
"""

NARRATION_MANIFEST_BATCH_PROMPT = """You are an art director storyboarding a 2D stickman story-cartoon explainer video.

The following universal art style is applied automatically to every frame, so NEVER repeat or mention it in your answers:
{style_prefix}

Recurring cast (must appear and be drawn identically in every frame, never redesign them):
{characters}

Below is a JSON array of narration beats. Each beat has an index, the narration text spoken at that moment, and its duration in seconds.
For EACH beat, write ONE rich, detailed storyboard description (60 to 110 words) of a single 16:9 frame that literally shows what is being narrated at that moment.

Every prompt MUST cover, in flowing prose:
1. Character(s): name who is present and describe their exact pose, gesture, body language, facial expression, gaze direction and what they are holding or doing.
2. Key objects/props: every important object, tool, animal or action named in the narration text must be visibly present and clearly described.
3. Setting/background: the specific location, time of day, weather and terrain (e.g. a rocky hillside at dusk, a cave mouth under a starry sky, a riverbank in thick mist).
4. Lighting and mood: the light sources and atmosphere (e.g. warm orange firelight against a cold dark sky, soft moonlight, glowing embers).
5. Composition: where the characters and key objects sit in the frame and any foreground/midground/background depth.

Hard rules:
- Keep character design, clothing, hair, colors and proportions identical across every beat; only change the action, pose, expression, camera angle and background.
- When the narration names a group or multiple characters, show all of them and describe each one's action.
- Concrete, vivid nouns. No abstraction, no camera/lens/ISO jargon, no mention of style, resolution, aspect ratio, or "no text".
- Never include text, captions, numbers, labels, logos or watermarks.
- Return one prompt per input beat, in the same order.

Beats:
{beats}

Return ONLY a JSON array shaped like:
[{{"index": 1, "prompt": "..."}}, {{"index": 2, "prompt": "..."}}]
"""

NARRATION_THUMBNAIL_PROMPT = """Design one high-CTR YouTube thumbnail concept for a stickman story-cartoon explainer video.

Title: {title}
Topic: {topic}
Universal art style (do NOT repeat it in your answer): {style_prefix}
Recurring cast (draw them identically): {characters}

Return ONLY a JSON object with this exact shape:
{{"prompt": "one bold, detailed 16:9 thumbnail description, 45 to 80 words: the recurring characters at the center in a dramatic, expressive pose (surprise, awe or fear), one big dominant object or event, a cinematic illustrated background with strong warm-versus-cool lighting and depth, high contrast, no text or logos"}}
"""

NARRATION_METADATA_PROMPT = """Write YouTube metadata for a narrated documentary video.

Topic: {topic}
Title: {title}
Script excerpt:
{script_excerpt}

Return ONLY a JSON object with this exact shape:
{{"title": "optimized title under 70 chars", "description": "2-4 paragraph description with a hook and a soft call to subscribe", "tags": ["tag1", "tag2", "tag3"]}}
"""
