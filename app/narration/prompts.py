"""LLM prompt templates for the narrated pipeline."""

NARRATION_SCRIPT_PROMPT = """You are a professional documentary scriptwriter for the YouTube channel "{channel}".

Write a complete, narration-only spoken script for a {duration_minutes}-minute video about:
{topic}

Hard requirements:
- Target about {word_target} spoken words (roughly 150 words per minute). Stay between {word_min} and {word_max} words.
- Open with a strong 10-15 second hook that poses the central question of the video.
- Follow a clear narrative arc: hook, context, evidence and concrete examples, a surprising turn, then a satisfying payoff.
- Keep a single consistent narrative voice and a friendly, engaging explainer tone.
- Ground claims in evidence. For history and prehistory, name the period and population being discussed; never present one group's observed routine as universal across human history.
- Distinguish archaeological evidence from modern ethnographic comparisons and from plausible reconstruction. Qualify uncertain routines and avoid unsupported precise statistics.
- When describing a day-in-the-life, make clear it is an illustrative reconstruction, then show varied tasks, cooperation, rest, and local environmental constraints.
- Preserve the user's supplied topic as the starting title; do not silently replace its central wording.
- Do NOT include scene directions, camera notes, timestamps, speaker labels, chapter titles, markdown, emojis, or bullet lists.
- Output plain continuous prose only, because the text is sent directly to a text-to-speech engine.

Return ONLY a JSON object with this exact shape:
{{"title": "short YouTube title", "hook": "the opening hook sentence", "script": "the full narration text"}}
"""

NARRATION_CHARACTER_BIBLE_PROMPT = """You are the art director and continuity lead for a cinematic documentary video.

Build a small, persistent character bible for this video. The same people must be
recognisable in every scene, so identity must be described with concrete,
visible details rather than adjectives. This is an illustrated documentary
reconstruction, not a cartoon and not a stick figure drawing.

Title: {title}
Topic: {topic}
Global visual style: {style_prefix}
Creative direction: {creative_direction}
Script excerpt:
{script_excerpt}

Rules:
- Create 1 to 3 recurring characters (prefer 2). Only include a character that the
  script actually needs. Do not invent named historical people.
- Each character needs a unique stable `id` (lowercase snake_case), a display name,
  and an `identity` paragraph covering apparent age, build, skin tone, face shape,
  eyes, hair, posture, and voice-free personality cues.
- `wardrobe` must be one fixed outfit that never changes. `distinguishing_features`
  should list 1-3 specific visual anchors (a scar, a bead necklace, a repaired sleeve).
- `palette` names the character's fixed clothing and accent colours.
- `reference_prompt` is a 25-45 word full-body studio reference: neutral warm grey
  backdrop, even soft light, standing relaxed, full figure in frame, no props that
  hide the body.
- `portrait_prompt` is a 20-35 word head-and-shoulders reference with the same face
  and outfit.
- `forbidden_changes` lists things the image generator must never alter.
- The style lock must describe medium, palette, lighting, level of detail, and
  camera language. It must explicitly exclude text, captions, logos and watermarks.
- Do not mention real actors, celebrities, franchises, or living people.
- Historical clothing should be a plausible illustrative reconstruction, not a
  claim of exact period accuracy.

Return ONLY a JSON object with this exact shape:
{{
  "style_lock": "one dense paragraph, 45-90 words",
  "notes": "one short continuity note",
  "characters": [
    {{
      "id": "lowercase_id",
      "name": "Display Name",
      "role": "primary|recurring|supporting",
      "identity": "60-110 words of visible identity detail",
      "wardrobe": "one fixed outfit, 20-45 words",
      "distinguishing_features": "1-3 specific visual anchors",
      "palette": "fixed colours",
      "reference_prompt": "full-body reference description",
      "portrait_prompt": "head-and-shoulders reference description",
      "forbidden_changes": ["...", "..."]
    }}
  ]
}}
"""

NARRATION_MANIFEST_BATCH_PROMPT = """You are an art director storyboarding a cinematic documentary illustration video.

The following global art style is applied automatically to every frame, so NEVER repeat or mention it in your answers:
{style_prefix}

The persistent cast is defined by a separate character bible. Use ONLY these ids when a beat shows one of them:
{characters}

Below is a JSON array of narration beats. Each beat has an index, the narration text spoken at that moment, and its duration in seconds.
For EACH beat, write ONE rich, detailed storyboard description (35 to 60 words) of a single 16:9 frame that literally shows what is being narrated at that moment. Put the subject and action first, then the setting, lighting, and composition. The previous and next beats are continuity context only; do not depict their events early or repeat the same composition.

Every prompt MUST cover, in flowing prose:
1. Subject(s): who or what is present, their exact pose, gesture, body language, facial expression, gaze direction and what they are holding or doing. If a recurring character appears, name them and use the same identity as the bible.
2. Key objects/props: every important object, tool, animal or action named in the narration text must be visibly present and clearly described.
3. Setting/background: the specific location, time of day, weather and terrain (e.g. a rocky hillside at dusk, a cave mouth under a starry sky, a riverbank in thick mist).
4. Lighting and mood: the light sources and atmosphere (e.g. warm orange firelight against a cold dark sky, soft moonlight, glowing embers).
5. Composition: where the subjects and key objects sit in the frame and any foreground/midground/background depth.
6. Continuity: carry forward a character, prop, location, or screen direction only when the neighbouring narration supports it; make this shot visibly advance the story.

Hard rules:
- Character identity, face, hair, body, clothing and colours never change. Only pose, expression, camera angle, lighting and environment change.
- When the narration names a group or multiple people, show all of them and describe each one's action.
- Do NOT force a recurring character into a beat that is about an object, landscape, diagram or abstract idea. Use an empty character list there.
- Concrete, vivid nouns. No abstraction, no camera/lens/ISO jargon, no mention of style, resolution, aspect ratio, or "no text".
- Never include text, captions, numbers, labels, logos or watermarks.
- Return one record per input beat, in the same order.

Each beat includes previous_beat and next_beat for story continuity. Use them as context, not extra narration to illustrate.

Beats:
{beats}

Return ONLY a JSON array shaped like:
[{{"index": 1, "prompt": "...", "character_ids": ["id_from_bible"], "negative_prompt": "optional extra exclusions"}}]
"""

NARRATION_THUMBNAIL_PROMPT = """Design a clear, curiosity-led YouTube thumbnail for a cinematic documentary video.

Title: {title}
Topic: {topic}
Universal art style (do NOT repeat it in your answer): {style_prefix}
Persistent cast (keep them identical): {characters}

Return ONLY a JSON object with this exact shape:
{{"prompt": "one bold, detailed 16:9 thumbnail image description, 45 to 80 words: one dominant expressive subject or unmistakable story object, one strong visual contrast, a simple location that reads at phone size, strong colour separation, clear negative space across the top for a later text overlay; no text, letters, logos or watermarks", "text": "a punchy question or contrast in 2 to 5 words, uppercase", "character_ids": ["id_from_bible"]}}
"""

NARRATION_METADATA_PROMPT = """Write YouTube metadata for a narrated documentary video.

Topic: {topic}
Title: {title}
Script excerpt:
{script_excerpt}

Return ONLY a JSON object with this exact shape:
{{"title": "optimized title under 70 chars", "description": "2-4 paragraph description with a hook and a soft call to subscribe", "tags": ["tag1", "tag2", "tag3"]}}
"""
