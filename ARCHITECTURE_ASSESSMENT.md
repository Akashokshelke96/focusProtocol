# ARCHITECTURE ASSESSMENT: YOUTUBE AUTOMATION ENGINE REWRITE

## CURRENT PIPELINE (BROKEN)

```
User Topic
    ↓
Gemini LLM
    ├─ Generates arbitrary educational script
    ├─ Creates random scene descriptions
    └─ Produces unrelated visual queries
    ↓
Scene Planner
    ├─ Creates varied, unrelated visual goals
    ├─ Generates random search terms
    └─ No visual consistency
    ↓
Multi-Provider Search
    ├─ Pexels: Random modern footage
    ├─ Pinterest: Unrelated imagery
    └─ No filtering for brand identity
    ↓
Media Download
    ├─ Accepts any matching result
    ├─ No quality gate
    └─ No character/style consistency
    ↓
Timeline Assembly
    ├─ Short shot durations (few seconds)
    ├─ Aggressive Ken Burns motion
    ├─ Rapid visual changes
    └─ Generic AI slideshow feel
    ↓
Narration/Captions
    ├─ Adds educational voiceover
    ├─ Overlays distracting text
    └─ Wrong format entirely for music channel
    ↓
FFmpeg Render
    ↓
OUTPUT: Random generic AI video that could be about anything
```

## WHY OUTPUT IS POOR

1. **No Brand DNA** - Every video looks different (different character, setting, mood, music)
2. **Wrong Format** - Built for educational content, not atmospheric music
3. **Visual Chaos** - Random images from random providers creating visual whiplash
4. **Narration-First** - Music is secondary to non-existent voice content
5. **Short Shots** - Images change every 5-10 seconds (MTV-style, not contemplative)
6. **Aggressive Motion** - Ken Burns zoom creates kinetic energy (wrong for blues channel)
7. **No Filtering** - Accepts any image that technically matches keywords
8. **No Character Consistency** - Random people, environments, eras
9. **Generic Music** - No controlled generation of dark blues identity

## SOLUTION: NEW TARGET PIPELINE

```
Channel Profile (FIXED, REUSABLE)
    ├─ Visual Identity
    │   ├─ Era: 1920s-1930s British noir
    │   ├─ Primary Subject: Gentleman gangster (Peaky Blinders archetype)
    │   ├─ Palette: Black, charcoal, dark blue, steel blue, muted amber
    │   ├─ Lighting: Low-key, noir, smoky, cinematic
    │   └─ Character: Consistent, smoking, sophisticated
    │
    ├─ Music Identity (FIXED)
    │   ├─ Genre: Dark Blues (55-80 BPM)
    │   ├─ Instrumental: TRUE
    │   ├─ Mood: Melancholic, lonely, masculine
    │   └─ Style: Smoky gentleman's club, late-night
    │
    └─ Video Standards (FIXED)
        ├─ Shot Duration: 30-75 seconds
        ├─ Motion: Very subtle (barely noticeable)
        ├─ Transitions: Crossfade only (1-3 seconds)
        └─ No narration, no captions
        
    ↓
    
Music Generation (PRIMARY)
    ├─ Gemini: Create detailed ACE-Step music prompt
    │   └─ (NOT arbitrary, follows music profile)
    │
    ├─ ACE-Step: Generate 4 music candidates
    │   ├─ Candidate A, B, C, D
    │   └─ All within dark blues profile
    │
    ├─ Audio Validation
    │   ├─ Duration check
    │   ├─ Quality check (no clipping, silence, artifacts)
    │   ├─ BPM validation
    │   └─ Energy level check
    │
    └─ Select: Best candidate → Music Library
    
    ↓
    
Visual Hero Image Set (SECONDARY TO MUSIC)
    ├─ Duration known: Music duration determines video length
    │
    ├─ Gemini: Generate 5-8 hero image prompts
    │   ├─ ALL constrained to channel profile
    │   ├─ NOT arbitrary creative invention
    │   └─ Built from profile components:
    │       ├─ Character (gentleman, smoking, suit, hat)
    │       ├─ Environment (office, pub, street, car)
    │       ├─ Action (smoking, looking out window, holding whiskey)
    │       ├─ Lighting (low-key, rim light, smoke backlit)
    │       └─ Color (dark blue-gray noir grade)
    │
    ├─ Pinterest Search (CONTROLLED)
    │   ├─ Search queries built from profile, NOT invented
    │   ├─ Heavy filtering for visual style match
    │   ├─ Reject: Modern, unrelated, wrong era, wrong character
    │   └─ Accept: Period noir, smoking, suits, atmospheric
    │
    ├─ Pexels Search (ATMOSPHERIC ONLY)
    │   ├─ Smoke, rain, fire, whiskey, city lights
    │   ├─ Supporting assets only
    │   └─ Never primary character source
    │
    ├─ Visual Quality Gate
    │   ├─ Character consistency (same archetype)
    │   ├─ Style scoring (0.0-1.0 profile fit)
    │   ├─ Aspect ratio (16:9 only)
    │   ├─ Resolution (1920x1080 minimum)
    │   ├─ Color (dark, cool, desaturated)
    │   └─ REJECT if score < 0.60
    │
    ├─ Color Grading (UNIFIED)
    │   ├─ Apply dark blues LUT to all sources
    │   ├─ Desaturate modern elements
    │   ├─ Increase contrast
    │   ├─ Crush blacks
    │   └─ Add subtle film grain
    │
    └─ Deduplication
        ├─ No random image repetition
        ├─ Smart reuse with different crops/motion
        └─ Quality > Quantity (reuse strong image vs use weak image)
    
    ↓
    
Timeline Assembly (MUSIC-DRIVEN)
    ├─ Music duration: e.g., 5 minutes (300 seconds)
    │
    ├─ Calculate shot allocation
    │   ├─ 5-6 hero images × 45 seconds avg
    │   └─ Crossfades: ~5 sec each
    │
    ├─ Assign durations
    │   ├─ Hero image A: 0:00-0:45
    │   ├─ Crossfade: 0:43-0:48
    │   ├─ Hero image B: 0:48-1:35
    │   └─ Continue...
    │
    ├─ Apply Subtle Motion
    │   ├─ Very slow zoom in/out (0.15 strength)
    │   ├─ Barely noticeable panning
    │   ├─ NO aggressive Ken Burns
    │   └─ Motion imperceptible to casual viewer
    │
    ├─ Apply Crossfades
    │   ├─ 1-3 second duration
    │   ├─ No glitches, flashes, or wipes
    │   └─ Simple dissolve only
    │
    └─ Timeline complete
    
    ↓
    
FFmpeg Render
    ├─ Input: Hero images + motion + music
    ├─ Output: 1920x1080, 30fps, H.264 + AAC
    └─ Result: Coherent dark blues visualizer
    
    ↓
    
OUTPUT: Music-first atmospheric video
    ├─ Looks like: One continuous noir film
    ├─ Feels like: Gentleman smoking alone in dark room
    ├─ Identity: Recognizable brand (Dark Blues)
    ├─ Character: Consistent protagonist
    ├─ Visual: Cohesive, non-random
    └─ Audio: Dark blues throughout
```

## KEY ARCHITECTURAL CHANGES

### 1. **Channel Profile System (NEW)**
- Create `config/channel_profile.json`
- Define fixed visual identity (era, character, palette, lighting)
- Define fixed music identity (genre, BPM, instrumentation)
- Define fixed video standards (shot duration, motion, transitions)
- **EVERY** generation uses this profile as constraints

### 2. **Music-First Pipeline (REVERSED)**
- Old: Visual story → find music
- New: **Music selected first** → visual timeline built to match duration
- ACE-Step generates multiple candidates
- Audio validation selects best candidate
- Video duration = Music duration (FIXED)

### 3. **Constrained Gemini (NOT freed)**
- Old: Gemini creates arbitrary educational script
- New: Gemini creates hero image prompts **from channel profile components**
- Gemini does NOT invent visual story
- Gemini assembles existing profile elements into prompts
- **Example**: "1920s British gentleman, smoking, dark office, low-key noir" (not arbitrary)

### 4. **Visual Quality Gate (NEW)**
- Calculate `visual_style_score` (0.0-1.0) for each candidate
- Reject score < 0.60
- Consider: era relevance, character match, palette match, composition, quality
- Better to reuse strong image than add weak image

### 5. **Long Shot Durations (CHANGED)**
- Old: 5-10 seconds per image
- New: **30-75 seconds per image** (configurable)
- Feels contemplative, not ADHD
- Supports music-driven pacing

### 6. **Subtle Motion (CHANGED)**
- Old: Aggressive Ken Burns (1.3-1.5 scale)
- New: **Very subtle** (1.02-1.04 scale)
- Motion barely noticeable
- Viewer shouldn't think "camera is moving"
- Should think "watching scene unfold"

### 7. **No Narration by Default (CHANGED)**
- Old: Generates script + captions + voiceover
- New: **Music channel, instrumental only**
- `NARRATION_ENABLED=false` by default
- No captions unless explicitly enabled

### 8. **Unified Color Grading (NEW)**
- Apply consistent LUT/grading to all sources
- All images should look like they're from same film
- Dark, cool, desaturated, high-contrast appearance

### 9. **Pinterest Controlled Usage (CHANGED)**
- Old: Random Pinterest searches
- New: Pinterest queries built from **profile only**
- Heavy filtering for style match
- Atmospheric, period, noir, gentleman-focused
- Reject: Modern, unrelated, wrong era

### 10. **Pexels Secondary Role (CHANGED)**
- Old: Pexels used for primary character footage
- New: Pexels for **atmospheric elements only**
  - Smoke, rain, fire, whiskey, city lights
  - Never as primary visual
  - Must match dark aesthetic

## COMPONENTS TO PRESERVE
- Job system ✓
- Database (SQLite) ✓
- Configuration system ✓
- FFmpeg infrastructure ✓
- Logging ✓
- Provider abstraction ✓
- Download utilities ✓

## COMPONENTS TO REMOVE/DISABLE
- Narration generation ✗
- Caption generation ✗
- Educational script pipeline ✗
- Random scene planning ✗
- Short shot durations (update timing) ✗
- Aggressive motion (reduce strength) ✗
- Random provider selection ✗

## COMPONENTS TO BUILD (NEW)
- Channel Profile system
- Visual style scorer
- Music prompt builder (detailed)
- ACE-Step integration (proper API usage)
- Audio quality validator
- Music candidate selection
- Music library with metadata
- Color grading pipeline
- Controlled image search (profile-constrained)
- Long shot timeline builder

## SUCCESS CRITERIA

The new system is successful when output **visibly resembles**:
- Dark gentleman noir visualizer
- Consistent character/world
- Long contemplative shots (30-75 sec)
- Dark blue-gray color grade
- Subtle barely-noticeable motion
- Smooth crossfades
- Dark blues music throughout
- NO random modern stock footage
- NO unrelated characters
- NO bright colors
- NO aggressive motion
- NO narration/captions
- Feels like one coherent film
