import base64
import requests
from pathlib import Path


# ============================================================
# ACE MUSIC CONFIG
# ============================================================

BASE_URL = "https://api.acemusic.ai"
API_KEY = "271fd1cf7aa14bda9b2227ec4c797cda"

OUTPUT_FILE = Path("party_song_5_minutes.mp3")


# ============================================================
# SONG PROMPT
# ============================================================

PROMPT = """
## ORIGINAL DARK MASCULINE FOCUS BLUES — MUSIC GENERATION PROMPT

Create an **ORIGINAL, DARK, SOPHISTICATED, HYPNOTIC BLUES / CINEMATIC BLUES TRACK** designed specifically for **deep work, coding, studying, writing, reading, late-night productivity and intense concentration**.

The track should feel like the soundtrack of a highly disciplined man working alone at **2 AM** — rain against the window, dim room, black coffee, laptop glowing, headphones on, phone turned off, completely disconnected from the outside world.

The psychological message is:

**DISCIPLINE OVER DISTRACTION.
FOCUS OVER COMFORT.
KEEP MOVING.
DO THE WORK.**

### CORE MUSICAL IDENTITY

Dark noir blues × cinematic blues × restrained blues-rock.

The mood should be:

* Masculine
* Mature
* Powerful
* Intelligent
* Mysterious
* Calm
* Disciplined
* Confident
* Inspirational
* Slightly dangerous
* Emotionally controlled

IMPORTANT:

This should NOT feel angry, aggressive, depressing or overly emotional.

It should feel like **quiet power**.

The listener should feel:

> "Nobody is coming to save me.
> I know what needs to be done.
> So I keep working."

But the music must remain relaxing enough to function as **background concentration music**.

---

## TEMPO & GROOVE

Target approximately **76–82 BPM**.

Slow, deliberate, steady groove with a subtle blues swing.

The rhythm should feel almost like a **steady heartbeat**.

Avoid energetic dance rhythms.

Avoid dramatic rhythmic changes.

Establish the groove quickly and maintain it for a long time.

The listener should be able to mentally lock into the rhythm and eventually stop consciously noticing it.

---

## HYPNOTIC STRUCTURE

The most important characteristic is **FLOW STATE**.

Do not constantly introduce new musical ideas.

Instead:

**REPETITION + MICRO-EVOLUTION.**

Build a small number of musical elements and allow them to evolve extremely slowly.

Use:

* Repeating bass pattern
* Recurring guitar motif
* Consistent drum pulse
* Subtle atmospheric textures
* Small guitar phrasing variations
* Occasional ghost notes
* Tiny rhythmic variations
* Very subtle harmonic movement

Changes should be felt subconsciously rather than obviously noticed.

Avoid:

* Huge drops
* Dramatic transitions
* Big buildups
* Sudden silence
* Massive climaxes
* Frequent chord changes
* Constant instrumental additions

The song should feel like it is **continuously moving forward without demanding attention**.

---

## DRUMS

Minimal, restrained, organic drums.

Use:

* Deep soft kick
* Dry controlled snare
* Subtle closed hi-hat
* Occasional ghost notes
* Very restrained percussion

Keep the drum pattern repetitive and predictable.

No EDM drums.

No trap hi-hat patterns.

No aggressive rock drumming.

No giant crashes.

No dramatic fills.

The drums should provide **momentum without stealing attention**.

---

## BASS

Deep, warm electric bass.

Slight analog/tape saturation.

Strong low-mid presence without excessive sub-bass.

Create a simple repeating blues-based bass pattern tightly synchronized with the kick.

Occasionally introduce:

* Chromatic passing notes
* Small rhythmic variations
* Slight slides

But keep everything restrained.

The bass should feel like the **engine of the track**.

Stable.

Heavy.

Controlled.

Repetitive.

---

## ELECTRIC GUITAR

Use a dark vintage electric guitar through a warm tube amplifier.

Tone:

* Warm
* Smoky
* Slightly dirty
* Smooth
* Thick
* Controlled
* Sustained

Use:

* Slow blues bends
* Slides
* Subtle vibrato
* Muted notes
* Short melodic phrases
* Long sustained notes
* Deliberate pauses

Create **1–2 extremely simple recurring guitar motifs**.

The motifs should become familiar through repetition.

Do NOT use:

* Shredding
* Fast solos
* Virtuoso playing
* Constant guitar fills
* Excessive distortion
* Flashy melodies

A single guitar phrase followed by silence should sometimes be more powerful than ten notes.

**Let the guitar breathe.**

---

# VOCALS / LYRICS

Include **VERY SPARSE, VERY SLOW, LOW-MALE VOCALS**.

The vocal should sound like a **deep, mature, masculine inner voice**, not a pop singer.

Vocal characteristics:

* Deep male baritone
* Low register
* Warm
* Slightly raspy
* Calm
* Controlled
* Confident
* Intimate
* Almost whispered at times
* Emotionally restrained

The vocal should feel like a man talking to himself while working late at night.

NOT theatrical.

NOT emotional crying.

NOT romantic.

NOT pop.

NOT rap.

NOT motivational-speaker style.

The voice should appear only occasionally.

There should be **long instrumental sections between vocal phrases**.

Lyrics should be extremely slow.

A short phrase may take several seconds to deliver.

Allow significant silence between lines.

The vocals must function as an **atmospheric motivational layer**, not the primary focus of the song.

---

# LYRIC THEMES

Lyrics should revolve around:

* Discipline
* Persistence
* Focus
* Patience
* Self-control
* Working while others sleep
* Ignoring distractions
* Quiet confidence
* Building something meaningful
* Becoming stronger
* Delayed gratification
* Consistency
* Finishing the work
* Moving forward
* Mental toughness

Avoid clichés and generic motivational slogans.

Avoid romance.

Avoid heartbreak.

Avoid sadness.

Avoid violence.

Avoid controversial subjects.

Avoid explicit language.

Avoid religious messaging.

Avoid political messaging.

Avoid overly complicated poetry.

The words should be **simple, masculine and memorable**.

Examples of the lyrical feeling:

"Keep going."

"Stay with the work."

"One more hour."

"Don't look back."

"Let the noise disappear."

"Build it slowly."

"Nobody has to know."

"Just keep moving."

"Finish what you started."

"Tomorrow belongs to the disciplined."

These are examples of the **tone and concept**, not lyrics to copy directly.

Write completely ORIGINAL lyrics.

---

# VOCAL PLACEMENT

Do NOT sing continuously.

Example conceptual structure:

**0:00–0:45**
Instrumental introduction. Establish the hypnotic groove.

**0:45–1:05**
One short deep vocal phrase.

**1:05–2:00**
Mostly instrumental.

**2:00–2:15**
Another sparse vocal phrase.

**2:15–3:15**
Extended instrumental flow.

**3:15–3:35**
Low male motivational phrase.

**3:35–4:30**
Instrumental groove with subtle guitar evolution.

**4:30–5:00**
Very restrained final vocal phrase followed by instrumental continuation.

The exact structure can vary, but the principle is:

**MUSIC FIRST. VOCALS SECOND.**

The listener should still be able to work comfortably without following the lyrics.

---

# HARMONY

Use a dark minor-blues harmonic language.

Blend:

* Minor blues
* Dominant seventh tension
* Blues scale
* Pentatonic vocabulary
* Occasional chromatic passing chords

Keep the harmonic progression simple.

Avoid complicated jazz harmony.

Avoid frequent key changes.

Avoid dramatic modulation.

The harmony should create a feeling of **controlled tension and forward movement**.

---

# ATMOSPHERE

Create a subtle nocturnal environment:

Rain outside.

Distant city ambience.

Dark room.

Warm analog equipment.

Late-night isolation.

Coffee.

Laptop glow.

Empty streets.

Do not make environmental sounds too obvious.

They should sit underneath the music almost subconsciously.

Possible subtle textures:

* Very quiet rain
* Distant room tone
* Soft tape hiss
* Subtle vinyl texture
* Faint atmospheric drones

No distracting sound effects.

---

# PRODUCTION

Warm analog-inspired production.

Use:

* Tape saturation
* Tube-style guitar warmth
* Smooth compression
* Controlled low frequencies
* Rich low-mid body
* Soft high frequencies
* Moderate stereo width
* Stable center image
* Natural room ambience

The master should be comfortable through headphones for **long work sessions**.

Avoid:

* Harsh treble
* Excessive sub-bass
* Over-compression
* Aggressive limiting
* Piercing hi-hats
* Excessive stereo movement
* Sudden volume changes

The listener should be able to keep the track playing for hours without fatigue.

---

# DYNAMICS

Maintain relatively consistent energy.

No huge climax.

No cinematic explosion.

No sudden drop.

No dramatic ending.

The song should feel like a **continuous mental state** rather than a traditional verse/chorus pop song.

Energy can increase very subtly over time through:

* Slightly thicker guitar texture
* Small bass variations
* Additional atmospheric layers
* Slightly stronger drums

But these changes must remain extremely subtle.

---

# MASTER PSYCHOLOGICAL EFFECT

The music should create this feeling:

**2 AM.
Everyone else is asleep.
The room is quiet.
The rain is falling.
The screen is glowing.
You have work to finish.
You don't need motivation.
You simply keep going.**

The listener should enter a state where:

**Distractions feel distant.
Time feels slower.
Thoughts become quieter.
The groove becomes familiar.
Work becomes easier.
Focus becomes automatic.**

The ideal reaction is:

> "I'll work for a few minutes."

And then:

> "Wait... how has it already been two hours?"

---

# ABSOLUTELY AVOID

NO EDM.

NO trap.

NO pop structure.

NO cheerful melodies.

NO romantic vocals.

NO emotional ballad.

NO sad breakup lyrics.

NO aggressive metal.

NO screaming.

NO rap.

NO fast singing.

NO high-pitched male vocals.

NO female vocals.

NO flashy guitar solos.

NO shredding.

NO excessive percussion.

NO dramatic orchestration.

NO massive cinematic impacts.

NO sudden drops.

NO constant chord changes.

NO constantly changing melodies.

NO catchy commercial chorus.

NO distracting vocal hooks.

NO overly inspirational "gym motivation" sound.

NO corporate motivational soundtrack feeling.

NO cheesy lyrics.

NO imitation of any existing artist or song.

---

# ORIGINALITY REQUIREMENT

Create a **completely original composition**.

Do not copy, recreate, interpolate or imitate any existing song, melody, riff, vocal performance, recording, arrangement or distinctive musical phrase.

The composition, lyrics, guitar motifs, bassline, vocal melodies and arrangement must all be original.

---

## FINAL CREATIVE DIRECTION

**DARK BLUES FOR PEOPLE WHO HAVE WORK TO DO.**

A slow masculine voice.

A hypnotic blues groove.

Rain outside.

Guitar breathing between phrases.

Deep bass.

Minimal drums.

Sparse words.

Quiet confidence.

No unnecessary drama.

No distractions.

Just controlled momentum.

**The music should not tell the listener to work harder.
It should make working feel natural.**

"""


# ============================================================
# LYRICS
# ============================================================

LYRICS = """
[Intro - Guitar Lick]

[Verse 1]
He's the shadow in the corner with a stare so cold
Walking slow, yeah he's got that golden soul
Averiskoval, quiet in the crowd
But the way he moves, you won't hear a sound
He's a whisper in the dark with a mind so sharp
A smooth operator, he's the king of his heart
With blood on his hands, no regrets in his tone
He's got a plan to make the city his own

[Chorus]
Averiskoval, the name they all fear
Got a heart of stone and a vision crystal clear
Averiskoval, the man they all see
But deep in the shadows, he's the man to be

[Guitar Solo]

[Verse 2]
He's the man you can't ignore, but don't you dare come near
He'll make you a bet you'll never feel that fear
He's the master of chaos, the one you can't tame
Averiskoval, you'll remember the name

[Guitar Lick]

[Verse 3]
In a world full of lies, he's the truth in disguise
With a mind so sharp, he's got that cool kind of style
He's theören, the one who's got that high power
No games, no games, the one who's got the power

[Guitar Solo]

[Verse 4]
He's the man you can't ignore, but don't you dare come near
He'll make you a bet you'll never feel that fear
He's the master of chaos, the one you can't tame
Averiskoval, you'll remember the name

[Instrumental Break]

[Bridge]
He's the shadow in the corner with a stare so cold
Walking slow, yeah he's got that golden soul
Averiskoval, quiet in the crowd
But the way he moves, you won't hear a sound
He's a whisper in the dark with a mind so sharp
A smooth operator, he's the king of his heart
With blood on his hands, no regrets in his tone
He's got a plan to make the city his own

[Chorus]
Averiskoval, the name they all fear
Got a heart of stone and a vision crystal clear
Averiskoval, the man they all see
But deep in the shadows, he's the man to be

[Guitar Solo]

[Verse 5]
In a world full of lies, he's the truth in disguise
With a mind so sharp, he's got that cool kind of style
He's theören, the one who's got that high power
No games, no games, the one who's got the power

[Guitar Lick]

[Verse 6]
In a world full of lies, he's the truth in disguise
With a mind so sharp, he's got that cool kind of style
He's theören, the one who's got that high power
No games, no games, the one who's got the power

[Verse 7]
He's the man you can't ignore, but don't you dare come near
He'll make you a bet you'll never feel that fear
He's the master of chaos, the one you can't tame
Averiskoval, you'll remember the name

[Instrumental Break]

[Verse 8]
In a world full of lies, he's the truth in disguise
With a mind so sharp, he's got that cool kind of style
He's theören, the one who's got that high power
No games, no games, the one who's got the power

[Verse 9]
He's the man you can't ignore, but don't you dare come near
He'll make you a bet you'll never feel that fear
He's the master of chaos, the one you can't tame
Averiskoval, you'll remember the name

[Outro]
[Scat singing]
In a world full of lies, he's the truth in disguise
With a mind so sharp, he's got that cool kind of style
He's theören, the one who's got that high power
No games, no games, the one who's got the power
[Final guitar chord and fade out]
"""


# ============================================================
# GENERATE SONG
# ============================================================

def generate_song():

    url = f"{BASE_URL}/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "curl/8.4.0",
    }

    payload = {
        "model": "acemusic/acestep-v1.5-turbo",

        "messages": [
            {
                "role": "user",
                "content": (
                    f"<prompt>{PROMPT}</prompt>\n"
                    f"<lyrics>{LYRICS}</lyrics>"
                ),
            }
        ],

        "audio_config": {
            "instrumental": True,
            "duration": 180,
            "format": "mp3",
        },

        "use_cot_caption": False,
    }

    print("=" * 60)
    print("ACE MUSIC - 5 MINUTE SONG GENERATOR")
    print("=" * 60)
    print()
    print("Generating song...")
    print("Duration: 300 seconds")
    print("Format: MP3")
    print()

    # ========================================================
    # API REQUEST
    # ========================================================

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=900,
    )

    print("HTTP Status:", response.status_code)

    # ========================================================
    # ERROR
    # ========================================================

    if response.status_code != 200:

        print()
        print("ACE MUSIC ERROR")
        print("-" * 60)
        print(response.text)
        print("-" * 60)

        response.raise_for_status()

    # ========================================================
    # JSON RESPONSE
    # ========================================================

    data = response.json()

    print("Generation finished.")
    print("Extracting audio...")
    print()

    # ========================================================
    # GET MESSAGE
    # ========================================================

    choices = data.get("choices")

    if not choices:
        raise RuntimeError(
            "No choices returned by ACE Music."
        )

    message = choices[0].get("message", {})

    # ========================================================
    # GET AUDIO
    # ========================================================

    audio = message.get("audio")

    if not audio:
        raise RuntimeError(
            "No audio returned by ACE Music.\n\n"
            + str(data)
        )

    # ========================================================
    # ACE MUSIC RESPONSE FORMAT
    #
    # audio = [
    #     {
    #         "audio_url": {
    #             "url": "data:audio/mpeg;base64,AAAA..."
    #         },
    #         "type": "audio_url"
    #     }
    # ]
    # ========================================================

    if not isinstance(audio, list):
        raise RuntimeError(
            f"Unexpected audio format: {type(audio)}"
        )

    if len(audio) == 0:
        raise RuntimeError(
            "ACE Music returned an empty audio list."
        )

    audio_item = audio[0]

    # Get audio_url object
    audio_url = audio_item.get("audio_url")

    if not audio_url:
        raise RuntimeError(
            "audio_url was not found in response.\n\n"
            + str(audio_item)
        )

    # Get actual URL
    audio_data_url = audio_url.get("url")

    if not audio_data_url:
        raise RuntimeError(
            "audio_url.url was not found.\n\n"
            + str(audio_url)
        )

    print("Audio data received.")
    print("Audio URL type:", audio_data_url[:30])
    print()

    # ========================================================
    # EXTRACT BASE64 FROM DATA URL
    #
    # data:audio/mpeg;base64,AAAA....
    # ========================================================

    if audio_data_url.startswith("data:"):

        try:
            header, audio_b64 = audio_data_url.split(
                ",",
                1
            )

        except ValueError:
            raise RuntimeError(
                "Invalid audio data URL."
            )

    else:

        # In case ACE Music returns raw Base64
        audio_b64 = audio_data_url

    # ========================================================
    # DECODE
    # ========================================================

    print("Decoding MP3...")

    try:

        audio_bytes = base64.b64decode(
            audio_b64
        )

    except Exception as e:

        raise RuntimeError(
            f"Could not decode audio Base64: {e}"
        )

    # ========================================================
    # SAVE MP3
    # ========================================================

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "wb"
    ) as f:

        f.write(audio_bytes)

    # ========================================================
    # SUCCESS
    # ========================================================

    print()
    print("=" * 60)
    print("           SONG GENERATED SUCCESSFULLY")
    print("=" * 60)
    print()
    print("File saved to:")
    print(OUTPUT_FILE.resolve())
    print()
    print(
        "File size:",
        f"{len(audio_bytes) / (1024 * 1024):.2f} MB"
    )
    print()
    print("Requested duration: 5 minutes")
    print("Format: MP3")
    print()
    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    if API_KEY == "YOUR_API_KEY_HERE":

        raise RuntimeError(
            "Please enter your ACE Music API key "
            "in the API_KEY variable."
        )

    generate_song()