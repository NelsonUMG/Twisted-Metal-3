"""End-to-end Lobby.run/advance + room directory + relay + two actual emulators.

Loopback only, temporary profiles/runtime folders, no user saves or accounts.
"""
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import threading
import tkinter as tk
from unittest.mock import patch

from verify_linked_startup import TestRelay, wait_for
from lobby_client import Lobby
from lobby_server import Directory, Handler

ROOT = Path(__file__).resolve().parent.parent


def main():
    relay = TestRelay()
    directory = Directory(':memory:', f'http://127.0.0.1:{relay.port}/tm3-relay', relay.secret)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    server.directory = directory
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
    thread.start()
    apps = []
    report = {}
    try:
        with tempfile.TemporaryDirectory(prefix='tm3_internet_lobby_qa_') as folder:
            base = Path(folder)
            for index in range(2):
                side = base / str(index)
                side.mkdir()
                exe = side / 'TM3Online.exe'
                shutil.copy2(ROOT/'TM3Online_Lobby/runtime/TM3Online.exe', exe)
                (side/'TM3Console.ini').write_text('[Console]\nMuted=1\nPlayer2Enabled=1\n', encoding='utf-8')
                root = tk.Tk()
                root.withdraw()
                with patch('lobby_client.DATA', side), patch('lobby_client.load_config', return_value={}):
                    app = Lobby(root)
                for timer in root.tk.call('after', 'info'):
                    root.after_cancel(timer)
                app.profile = dict(name='RelayQA' + str(index), secret=secrets.token_hex(32))
                app.profile_path = side/'profile.json'
                app.config = dict(directory_url=f'http://127.0.0.1:{server.server_port}', runtime=dict(
                    executable=str(exe), core=str(ROOT/'TM3Online_Lobby/runtime/cores/beetle_psx_libretro.dll'),
                    game=str(ROOT/'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.cue'),
                    environment=dict(TM3O_LINK_HIRES_WAIT='1', TM3O_LINK_UDP_WAKE='1', TM3O_CPU_BUDGET_PERCENT='175')))
                apps.append(app)
            # launch_game reads DATA at runtime, so give the host and guest
            # distinct session-state names inside one shared disposable folder.
            with patch('lobby_client.DATA', base):
                for app in apps:
                    app.worker = threading.Thread(target=app.run, daemon=True)
                    app.worker.start()
                wait_for(lambda: all(a.token for a in apps), 8, 'Lobby login failed')
                host, guest = apps
                host.action('create', description='Isolated real relay QA')
                wait_for(lambda: bool(directory.rooms), 5, 'Room creation failed')
                room = next(iter(directory.rooms.values()))
                guest.action('join', room=room['id'])
                wait_for(lambda: len(room['players']) == 2, 5, 'Room join failed')
                host.action('start')
                def connected():
                    return all(a.session_state().get('state') == 'connected' for a in apps)
                def detail():
                    return f"Startup failed: phase={room['phase']}, error={room['error']}, states={[a.session_state() for a in apps]}"
                wait_for(connected, 35, detail)
                assert all(a.relay_bridge and not a.relay_bridge.error for a in apps)
                assert all(a.session_state().get('player2_enabled') for a in apps)
                report['first_start'] = report['second_controller_enabled'] = True
                guest.return_room_process()
                wait_for(lambda: all(a.session_state().get('state') == 'returned' for a in apps), 15, 'Cancel failed')
                wait_for(lambda: room['phase'] == 'waiting', 5, 'Directory did not return to waiting')
                assert all(a.session_state().get('transport_connected') for a in apps)
                report['cancel_keeps_transport'] = True
                generation = room['generation']
                host.action('start')
                wait_for(lambda: room['generation'] > generation and connected(), 35, detail)
                report['second_start_fresh_generation'] = True
                for app in apps:
                    app.close()
                report['owned_processes_closed'] = all(a.process is None and a.relay_bridge is None and not a.worker.is_alive() for a in apps)
                assert report['owned_processes_closed']
                apps.clear()
        target = ROOT/'diagnostics/internet_relay_v1/lobby_end_to_end.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        for app in apps:
            app.close()
        server.shutdown(); server.server_close(); thread.join(timeout=2)
        directory.db.close()
        relay.close()


if __name__ == '__main__':
    main()
