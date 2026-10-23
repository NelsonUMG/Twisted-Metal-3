"""Real public directory + actual Lobby START/cancel/restart, no WAN simulation."""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'network'))
from lobby_client import Lobby
from directory_defaults import PUBLIC_DIRECTORY_URL


def main():
    apps = []; report = {}; work = ROOT/'diagnostics/system256_integration'
    def wait(predicate, seconds):
        deadline = time.monotonic()+seconds
        while time.monotonic()<deadline:
            for app in apps: app.root.update()
            if predicate(): return
            time.sleep(.02)
        raise AssertionError([(a.session_state(), a.last_error, a.room) for a in apps])
    with tempfile.TemporaryDirectory(prefix='tm3_system256_lobby_') as temporary:
        with patch.dict(os.environ, SDL_VIDEODRIVER='dummy'), patch('lobby_client.DATA', Path(temporary)):
            try:
                for side in (0,1):
                    root = tk.Tk(); root.withdraw()
                    config = dict(directory_url=PUBLIC_DIRECTORY_URL,
                                  system256=dict(enabled=True, assets=str(work/'assets')))
                    with patch('lobby_client.load_config', return_value=config): app = Lobby(root)
                    app.profile = dict(name=f'S256QA{side}'+secrets.token_hex(3), secret=secrets.token_hex(32))
                    app.profile_path = Path(temporary)/f'profile{side}.json'
                    app.language_path = ROOT/'TM3Online_Lobby/runtime/TM3Console.ini'
                    apps.append(app)
                    app.worker = threading.Thread(target=app.run, daemon=True); app.worker.start()
                wait(lambda: all(a.token for a in apps), 15)
                host, guest = apps
                host.action('create', description='QA SYSTEM256 integration')
                wait(lambda: host.room is not None, 10)
                guest.action('join', room=host.room['id'])
                wait(lambda: guest.room is not None and len(host.room['players'])==2, 10)
                for attempt in (1,2):
                    host.action('start')
                    wait(lambda: all(a.room and a.room['phase']=='playing' and
                                     a.session_state().get('state')=='connected' for a in apps), 45)
                    report[f'start{attempt}'] = True
                    guest.return_room_process()
                    wait(lambda: all(a.room and a.room['phase']=='waiting' for a in apps), 15)
                    wait(lambda: all(a.process is None or a.process.poll() is not None for a in apps), 10)
                    report[f'cancel{attempt}'] = True
                report.update(passed=True, real_public_directory=True, real_ice=True,
                              simulated_latency=False, actual_remote_wan=False)
                (work/'lobby_result.json').write_text(json.dumps(report, indent=2)); print(report)
            finally:
                for app in apps: app.close()


if __name__=='__main__': main()
