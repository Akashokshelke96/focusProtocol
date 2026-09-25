"""Private OAuth files; channel profiles never contain client secrets."""
import os
import subprocess
from pathlib import Path
from app.youtube.state import write_json


def private_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        import csv
        from app.utils.ffmpeg import no_window_flags
        result = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                                capture_output=True, text=True, check=True, **no_window_flags())
        sid = next(csv.reader([result.stdout.strip()]))[1]
        result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                                 f'*{sid}:(OI)(CI)F'], capture_output=True, **no_window_flags())
        if result.returncode:
            raise RuntimeError('Could not restrict access to the channel credentials directory')
    else:
        path.chmod(0o700)
    return path


def save_client(channel_id, client_id, client_secret, redirect_uri):
    directory = private_directory(Path('jobs/studio/credentials') / channel_id)
    path = directory / 'client_secrets.json'
    write_json(path, {'web': dict(client_id=client_id, client_secret=client_secret,
                                redirect_uris=[redirect_uri],
                                auth_uri='https://accounts.google.com/o/oauth2/auth',
                                token_uri='https://oauth2.googleapis.com/token')})
    if os.name != 'nt':
        path.chmod(0o600)
