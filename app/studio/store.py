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
        return read_json(self.root / 'operations.json', {
            'version': 1, 'channels': [Channel(id='focus-protocol', name='Focus Protocol').model_dump()],
            'profiles': [p.model_dump() for p in DEFAULT_PROFILES], 'content': [], 'batches': [],
            'paused': True, 'activity': [], 'assets': {},
        })

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
