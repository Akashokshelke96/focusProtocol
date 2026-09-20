"""Channel-scoped content planning using the existing LLM and filesystem history."""
import json
import random
import re
from difflib import SequenceMatcher
from app.studio.profiles import metadata_for


def normalized(value):
    return ' '.join(re.findall(r'\w+', value.casefold()))


def repeated(title, history):
    key = normalized(title)
    return any(key == normalized(old) or SequenceMatcher(None, key, normalized(old)).ratio() > .82 for old in history)


def create_plan(llm, profile, channel, minutes, history):
    error = None
    try:
        response = llm._generate_with_retry(
            'Plan one original instrumental music video for this channel and profile. '
            'Use a distinct setting, listening activity and musical mood; avoid paraphrases of history. '
            'No narration and exactly one full-duration background scene. Return JSON with '
            'concept (short title), description, tags (list), keywords (list), thumbnail_concept, '
            'visual_direction, music_direction. Do not use another channel\'s branding.\n' +
            json.dumps(dict(channel=channel['name'], profile=profile, minutes=minutes, avoid=history[-200:])),
            max_retries=1)
        plan = llm._extract_json(response)
        for key in ('concept', 'description', 'thumbnail_concept', 'visual_direction', 'music_direction'):
            if not isinstance(plan.get(key), str) or not plan[key].strip():
                raise ValueError('Content response is missing ' + key)
        if len(plan['concept']) > 80 or repeated(plan['concept'], history):
            raise ValueError('Content response repeats history or has an overlong title')
        for key in ('tags', 'keywords'):
            if not isinstance(plan.get(key), list) or not all(isinstance(t, str) for t in plan[key]):
                raise ValueError('Content response has invalid ' + key)
        plan['source'] = 'llm'
    except Exception as exc:
        error = str(exc)[:500]
        # A bounded, explicit local fallback, drawn without replacement against history.
        settings = ['Rain at the Observatory', 'The Last Train Home', 'Sunday in the Greenhouse',
                    'Letters from the Coast', 'Snow Outside the Bookshop', 'Dawn on the Rooftop',
                    'The Empty Theatre', 'Lanterns by the River', 'A Cabin above the Clouds',
                    'The Night Ferry', 'Autumn in the Courtyard', 'A Window over the City',
                    'The Lighthouse Keeper', 'An Afternoon in the Attic', 'The Desert Motel',
                    'A Table in the Garden', 'Midnight at the Museum', 'The Mountain Railway',
                    'After the Summer Storm', 'The Harbour before Sunrise']
        activities = [('Reading', 'a quiet reading session'), ('Reflection', 'unhurried reflection'),
                      ('Sketching', 'drawing and creative work'), ('Unwinding', 'winding down'),
                      ('Writing', 'journaling and writing'), ('Focus', 'sustained concentration'),
                      ('Rest', 'a peaceful break'), ('Evening', 'a calm evening')]
        options = [(f'{scene} — {label}', scene, activity) for scene in settings for label, activity in activities]
        random.SystemRandom().shuffle(options)
        used = {normalized(old) for old in history}
        selected = next((v for v in options if normalized(v[0]) not in used), None)
        if not selected:
            raise ValueError('Distinct local concepts exhausted. Restore the content provider or revise the profile.') from exc
        concept, scene, activity = selected
        plan = dict(concept=concept, description=f"{minutes} minutes of {profile['niche']} for {activity}. {scene} inspires this session for {channel['name']}.",
                    tags=profile['tags'], keywords=[profile['niche'], activity, scene],
                    thumbnail_concept=f'{scene}; clear focal point and space for a short headline',
                    visual_direction=f"{profile['visual_prompt']}. Setting: {scene}.",
                    music_direction=f"{', '.join(profile['genres'])}; {profile['listening_intent']}; suited to {activity}", source='local_fallback')
    plan['provider_error'] = error
    plan['scene_structure'] = [dict(start_seconds=0, duration_seconds=minutes*60, visual=plan['visual_direction'])]
    plan['narration'] = None
    plan['metadata'] = metadata_for(profile, channel, plan['concept'], minutes)
    plan['metadata'].update(youtube_description=plan['description'][:1200], youtube_tags=plan['tags'][:12])
    return plan
