"""Atomic filesystem state with one process/thread writer per transaction."""
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from app.youtube.state import write_json, publishing_lock
from app.studio.profiles import Channel, DEFAULT_PROFILES


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


class StudioStore:
    def __init__(self, root='jobs/studio'):
        self.root = Path(root)
        self.guard = threading.RLock()

    def read(self):
        state = read_json(self.root / 'operations.json', {
            'version': 1, 'channels': [Channel(id='focus-protocol', name='Camping With Blues').model_dump()],
            'profiles': [p.model_dump() for p in DEFAULT_PROFILES], 'content': [], 'batches': [],
            'paused': True, 'activity': [], 'assets': {},
        })

        if not any(p['id'] == 'blues' for p in state['profiles']):
            state['profiles'].append(next(p.model_dump() for p in DEFAULT_PROFILES if p.id == 'blues'))
        for channel in state['channels']:
            if channel['id'] == 'focus-protocol' and channel['name'] == 'Focus Protocol':
                channel.update(name='Camping With Blues', profile_id='blues', watermark_enabled=False)
        return state

    @contextmanager
    def transaction(self):
        with self.guard, publishing_lock(self.root):
            state = self.read()
            yield state
            write_json(self.root / 'operations.json', state)

    def channel(self, channel_id):
        channel = next((c for c in self.read()['channels'] if c['id'] == channel_id), None)
        if not channel:
            raise ValueError('Unknown channel')
        return channel
