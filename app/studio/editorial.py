"""Small metadata checks and real-timeline description assembly; no media work."""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


def normalized(value):
    return ' '.join(re.findall(r'\w+', str(value).casefold()))


def tokens(value):
    return set(normalized(value).split()) - {'the', 'a', 'an', 'for', 'of', 'and', 'with', 'in', 'at', 'to', 'by'}


def repeated(title, history):
    key, words = normalized(title), tokens(title)
    for old in history:
        other = normalized(old)
        overlap = words & tokens(old)
        union = words | tokens(old)
        if key == other or SequenceMatcher(None, key, other).ratio() > .82:
            return True
        if len(overlap) >= 3 and union and len(overlap)/len(union) >= .72:
            return True
    return False


def recent_content(root='jobs', channel_id='focus-protocol', limit=100):
    """Bounded read-only scan; old jobs are never migrated or rewritten."""
    records = []
    paths = sorted(Path(root).glob('*/metadata.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('channel_id', 'focus-protocol') != channel_id:
                continue
            plan = data.get('content_plan') or {}
            records.append(dict(title=data.get('youtube_title', ''), concept=plan.get('concept', ''),
                                theme=plan.get('theme', ''), mood=plan.get('mood', ''),
                                description=data.get('youtube_description', '')[:450],
                                session_titles=data.get('session_titles', plan.get('session_titles', []))))
            if len(records) >= limit:
                break
        except (OSError, ValueError, TypeError):
            continue
    return list(reversed(records))


def history_records(history):
    records = []
    for row in history[-200:]:
        if not isinstance(row, dict):
            row = {'title': str(row), 'concept': str(row)}
        records.append({key: row.get(key, '') for key in ('title', 'concept', 'theme', 'mood')})
        records[-1].update(description=str(row.get('description', ''))[:450],
                           session_titles=row.get('session_titles', [])[-240:])
    return records


def clean_list(value, maximum, name):
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f'{name} must be a nonempty list of strings')
    result = list(dict.fromkeys(v.strip() for v in value))
    if len(result) > maximum:
        raise ValueError(f'Too many {name}')
    return result


def validate_plan(plan, profile, channel, history):
    if not isinstance(plan, dict):
        raise ValueError('Expected a JSON object')
    history = history_records(history)
    for key in ('concept', 'theme', 'mood', 'description', 'visual_direction', 'music_direction', 'thumbnail_concept'):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            raise ValueError('Missing ' + key)
        plan[key] = plan[key].strip()
    concept = plan['concept']
    if not 8 <= len(concept) <= 80 or repeated(concept, [r.get('concept', '') for r in history]):
        raise ValueError('Concept is overlong or repeats recent content; choose a different scene and theme')
    if sum(normalized(r.get('theme', '')) == normalized(plan['theme']) for r in history[-10:]) >= 2:
        raise ValueError('Choose a different emotional theme from recent sessions')
    keywords = clean_list(plan.get('primary_keywords'), 3, 'primary_keywords')
    if any(not 4 <= len(k) <= 50 for k in keywords):
        raise ValueError('Use natural, specific keyword phrases')
    candidates = clean_list(plan.get('title_candidates'), 3, 'title_candidates')
    valid = []
    old_titles = [r.get('title', '') for r in history]
    for title in candidates:
        title = title.strip(' "“”')
        words = normalized(title).split()
        if (not 40 <= len(title) <= 95 or any(c in title for c in '\n<>#') or title.isupper()
                or any(words.count(word) > 2 for word in set(words) - {'the', 'for', 'and'})
                or repeated(title, old_titles) or keywords[0].casefold() not in title[:75].casefold()
                or not tokens(concept) & tokens(title)):
            continue
        opening = ' '.join(words[:3])
        if sum(normalized(old).startswith(opening) for old in old_titles[-12:]) >= 2:
            continue
        score = (20 if 55 <= len(title) <= 80 else 10) + (10 if keywords[0].casefold() in title[:60].casefold() else 0)
        score += len(tokens(concept) & tokens(title)) * 2
        style = next((mark for mark in ('|', '—', ':', ' for ') if mark in title), 'plain')
        score -= 6 * sum(style in old if style != 'plain' else not any(m in old for m in ('|', '—', ':', ' for '))
                         for old in old_titles[-5:])
        valid.append((score, title))
    if not valid:
        raise ValueError('No distinct, readable title with the primary phrase and concept; vary the opening/structure')
    banned = [str(p).casefold() for p in profile.get('avoid_phrases', []) if p]
    valid = [(score, title) for score, title in valid if not any(p in title.casefold() for p in banned)]
    if not valid:
        raise ValueError('Title contains a prohibited profile phrase')
    title = max(valid, key=lambda row: row[0])[1]
    description = plan['description']
    combined = title + '\n' + description
    if (len(description) < 650 or len(description.encode('utf-8')) > 4000
            or re.search(r'https?://|www\.|youtu\.be|\b\w+\.(?:com|net|org)\b|\b\d{1,2}:\d{2}(?::\d{2})?\b', combined, re.I)
            or any(c in combined for c in '<>') or '#' in description
            or re.search(r'\b(?:insert here|lorem ipsum|your channel|channel name|TBD)\b', combined, re.I)):
        raise ValueError('Description must be original complete prose (650–4000 UTF-8 bytes), without URLs, timestamps, hashtags or placeholders')
    if keywords[0].casefold() not in description[:250].casefold():
        raise ValueError('Use the primary keyword naturally in the opening 250 characters')
    if not tokens(concept) & tokens(description[:500]):
        raise ValueError('Opening does not match the concept')
    if 'perfect for' not in description.casefold() or not 3 <= len(re.findall(r'(?m)^\s*[•\-] ', description)) <= 5:
        raise ValueError('Include a concise PERFECT FOR list of 3–5 relevant activities')
    if channel['name'].casefold() not in description.casefold() or 'subscrib' not in description.casefold():
        raise ValueError('Include the actual channel name and a natural subscribe invitation')
    for match in re.finditer(r'(?:welcome to|subscribe to)\s+([^.!\n]+)', description, re.I):
        if channel['name'].casefold() not in match.group(1).casefold():
            raise ValueError('Use only the supplied channel identity')
    sentences = [normalized(s) for s in re.split(r'[.!?\n]+', description) if len(s.split()) > 7]
    if len(sentences) != len(set(sentences)):
        raise ValueError('Repeated sentences in description')
    opening = description.split('\n\n')[0]
    if any(repeated(opening, [r.get('description', '').split('\n\n')[0]]) for r in history if r.get('description')):
        raise ValueError('Description opening repeats recent content')
    tags = clean_list(plan.get('tags'), 12, 'tags')
    support = tokens(combined + ' ' + plan['theme'] + ' ' + plan['mood'] + ' ' + channel['name'])
    tags = [t for t in keywords + tags if 3 <= len(t) <= 50 and tokens(t) <= support and not re.search(r'[#<>\n@]', t)]
    tags = list({normalized(t): t for t in tags}.values())[:10]
    if len(tags) < 5 or keywords[0].casefold() not in [t.casefold() for t in tags]:
        raise ValueError('Provide 5–10 relevant tags supported by the title/description, primary keyword first')
    if sum(len(t) + (2 if ' ' in t else 0) for t in tags) + len(tags)-1 > 400:
        raise ValueError('Tags are too crowded; stay below 400 characters including API quoting')
    hashtags = clean_list(plan.get('hashtags'), 5, 'hashtags')
    compact = re.sub(r'\W', '', combined + channel['name']).casefold()
    if len(hashtags) < 3 or any(len(h) > 50 or not re.fullmatch(r'#[\w]+', h) or h[1:].casefold() not in compact for h in hashtags):
        raise ValueError('Use 3–5 relevant hashtags, each reflected in the prose or channel name')
    names = clean_list(plan.get('session_titles'), 12, 'session_titles')
    old_names = [n for r in history for n in r.get('session_titles', [])]
    if len({normalized(n) for n in names}) != 12 or any(not 3 <= len(n) <= 40 or re.search(r'\btrack\s*\d|https?://|[<>\n]', n, re.I) or repeated(n, old_names) for n in names):
        raise ValueError('Provide 12 original short editorial session labels, without generic track numbers or recent repeats')
    plan.update(title=title, title_candidates=[t for _, t in valid], primary_keywords=keywords,
                tags=tags, hashtags=hashtags, session_titles=names)
    return plan


def apply_tracklist(metadata):
    """Only new editorial packages, only measured starts from audio assembly."""
    if metadata.get('metadata_version') != 2:
        return
    plan = metadata.get('content_plan') or {}
    base = plan.get('description', metadata.get('editorial_description', ''))
    hashtags = plan.get('hashtags', metadata.get('hashtags', []))
    timeline = metadata.get('audio_track_timeline', [])
    aliases = plan.get('session_titles', metadata.get('session_titles', []))
    # Editorial names only, always: cycle the session labels across every
    # timeline track. Raw source filenames must never reach a description.
    if not aliases:
        metadata.update(tracklist_source='unavailable')
        return
    chapters = []
    for i, track in enumerate(timeline):
        start = float(track['start_seconds'])
        if not 0 <= start < metadata['target_duration_seconds']:
            continue
        name = re.sub(r'[<>\r\n]', '', aliases[i % len(aliases)])[:80]
        chapters.append(dict(start_seconds=start, title=name, source_filename=track['filename']))
    lines = []
    for chapter in chapters:
        seconds = int(chapter['start_seconds'])
        stamp = f'{seconds//60:02}:{seconds%60:02}' if seconds < 3600 else f'{seconds//3600}:{seconds%3600//60:02}:{seconds%60:02}'
        lines.append(f"{stamp} {chapter['title']}")
    block = '\n\nTRACKLIST & TIMESTAMPS\n' + '\n'.join(lines) if lines else ''
    if lines:
        block += '\nTimings follow the actual mix, including crossfades.'
        block += ' Session labels are editorial, not original song credits.'
    suffix = '\n\n' + ' '.join(hashtags)
    # No tracklist block in public descriptions: chapters/timestamps stay in
    # metadata only (session_chapters below). Prose + hashtags ship as-is.
    block = ''
    description = base + suffix
    metadata.update(youtube_description=description, session_chapters=chapters,
                    tracklist_source='audio_assembly' if chapters else 'unavailable')
