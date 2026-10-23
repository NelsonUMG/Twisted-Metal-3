"""Real Worker runtime + 3 lobby UIs + two emulators, no manual ICE codes.

The Worker defaults to LOCAL Miniflare; --public-url uses the real service.
Game ICE always crosses the user-space NAT lab, NOT real mobile Internet.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'network'))
from lobby_client import Lobby
from ice_nat_lab import NatNetwork, SimulatedP2PSession, isolated_ice_addresses, PUBLIC_IPS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-url')
    args = parser.parse_args()
    if args.public_url:
        from urllib.parse import urlsplit
        parsed = urlsplit(args.public_url)
        assert parsed.scheme == 'https' and parsed.hostname
        assert not (parsed.username or parsed.password or parsed.query or parsed.fragment)
    apps, games, networks = [], [], []
    report = dict(real_cloudflare_deployment=bool(args.public_url), real_wan_test=False,
                  manual_codes_used=False, game_network_simulated=True)
    node = None
    if not args.public_url:
        node = subprocess.Popen(['node.exe', str(ROOT / 'network/cloudflare/lab.mjs')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
    spawn = subprocess.Popen
    count = 0
    lock = threading.Lock()

    def factory(ice_servers=None):
        nonlocal count
        with lock:
            side = count % 2
            if side == 0:
                networks.append(NatNetwork())
            network = networks[-1]
            count += 1
        return SimulatedP2PSession(network, side)

    def hidden_spawn(*args, **kwargs):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        kwargs['startupinfo'] = startup
        process = spawn(*args, **kwargs)
        games.append(process)
        return process

    def wait(predicate, seconds, label):
        deadline = time.monotonic() + seconds
        while True:
            for app in apps:
                app.root.update()
            if predicate():
                return
            if time.monotonic() >= deadline:
                raise AssertionError(label + ': ' + str([(a.status.cget('text'), a.last_error, a.room, a.session_state()) for a in apps]))
            time.sleep(.02)

    try:
        url = (args.public_url or json.loads(node.stdout.readline())['url']).rstrip('/')
        if args.public_url:
            report['endpoint'] = url
        with ExitStack() as stack:
            folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='tm3_auto_rooms_qa_')))
            stack.enter_context(patch('lobby_client.DATA', folder))
            stack.enter_context(isolated_ice_addresses())
            stack.enter_context(patch('p2p_session.P2PSession', new=factory))
            stack.enter_context(patch('lobby_client.subprocess.Popen', new=hidden_spawn))
            stack.enter_context(patch.dict(os.environ, {'TM3_LOBBY_URL': url}))
            try:
                suffix = ' ' + secrets.token_hex(3)
                for index, name in enumerate(('QA Host', 'QA Guest', 'QA Observer')):
                    side = folder / str(index)
                    side.mkdir()
                    exe = side / 'TM3Online.exe'
                    shutil.copy2(ROOT / 'TM3Online_Lobby/runtime/TM3Online.exe', exe)
                    (side / 'TM3Console.ini').write_text('[Console]\nLanguage=1\nMuted=1\nPlayer2Enabled=1\n', encoding='utf-8')
                    root = tk.Tk(); root.withdraw()
                    with patch('lobby_client.DATA', side), patch('lobby_client.load_config', return_value={}):
                        app = Lobby(root)
                    app.profile = dict(name=name + suffix, secret=secrets.token_hex(32))
                    app.config = dict(directory_url=url, runtime=dict(executable=str(exe),
                        core=str(ROOT / 'TM3Online_Lobby/runtime/cores/beetle_psx_libretro.dll'),
                        game=str(ROOT / 'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.cue'),
                        environment=dict(TM3O_LINK_HIRES_WAIT='1', TM3O_LINK_UDP_WAKE='1', TM3O_CPU_BUDGET_PERCENT='175')))
                    apps.append(app)
                wait(lambda: all(a.token for a in apps), 15, 'Directory login failed')
                host, guest, observer = apps
                assert all(not hasattr(a, 'p2p_button') for a in apps)
                with patch('lobby_client.simpledialog.askstring', return_value='Sala automática TM3'):
                    host.create_room()
                wait(lambda: host.room and all(host.room['id'] in a.visible_rooms for a in apps), 8, 'Room not visible to everyone')
                rid = host.room['id']
                report['shared_room_list'] = True
                guest.table.selection_set(rid)
                guest.join()
                wait(lambda: all(a.room and len(a.room['players']) == 2 for a in (host, guest)), 8, 'Join failed')
                assert observer.room is None
                report['create_and_join_without_codes'] = True
                host.action('chat', text='Hola desde el lobby automático')
                wait(lambda: 'Hola desde el lobby automático' in guest.chat_log.get('1.0', 'end'), 8, 'Room chat failed')
                assert observer.visible_rooms[rid]['transport'] is None
                report['private_chat'] = True
                host.action('start')
                wait(lambda: all(a.session_state().get('state') == 'connected' for a in (host, guest)), 60, 'Automatic game start failed')
                report['actual_emulators_connected'] = True
                wait(lambda: all(a.ice_peer and a.ice_peer.latency_snapshot()['samples'] and
                                 not a.ice_peer.latency_snapshot()['stale'] and
                                 'RTT' in a.room_latency.cget('text') for a in (host, guest)),
                     8, 'Live peer ping did not appear')
                report['live_peer_ping_visible'] = True
                report['peer_latency'] = [a.ice_peer.latency_snapshot() for a in (host, guest)]
                assert all(a.session_state().get('player2_enabled') for a in (host, guest))
                report['second_controller_enabled'] = True
                report['ice_paths'] = [a.ice_peer.selected_path() for a in (host, guest)]
                assert all(path and path[0]['remote'][0] in PUBLIC_IPS for path in report['ice_paths'])
                wait(lambda: all(a.room['phase'] == 'playing' for a in (host, guest)), 8, 'Room not playing')
                guest.return_room_process()
                wait(lambda: all(a.session_state().get('state') == 'returned' and a.room['phase'] == 'waiting' for a in (host, guest)), 18, 'Cancel did not return both to waiting')
                assert all(a.session_state().get('transport_connected') for a in (host, guest))
                report['cancel_preserves_native_transport'] = True
                host.action('start')
                wait(lambda: all(a.room['generation'] == 2 and a.room['phase'] == 'playing' and a.session_state().get('state') == 'connected' for a in (host, guest)), 60, 'Second automatic START failed')
                report['second_start_new_generation'] = True
                wait(lambda: all(a.ice_peer.latency_snapshot()['samples'] and
                                 'RTT' in a.room_latency.cget('text') for a in (host, guest)),
                     8, 'Ping did not restart with the new session')
                report['peer_ping_new_generation'] = True
                guest.action('leave')
                wait(lambda: guest.room is None and host.room and len(host.room['players']) == 1, 10, 'Leave failed')
                host.action('leave')
                wait(lambda: rid not in observer.visible_rooms, 10, 'Closed room stayed visible')
                report['closed_room_removed'] = True
                for app in apps:
                    app.close()
                apps.clear()
                report['owned_emulators_closed'] = all(p.poll() is not None for p in games)
                assert report['owned_emulators_closed']
                report['passed'] = True
            finally:
                for app in apps:
                    app.close()
    finally:
        if node and node.poll() is None:
            node.stdin.write('stop\n'); node.stdin.flush()
            try:
                node.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                node.terminate(); node.wait(timeout=3)
        report['networks'] = [network.snapshot() for network in networks]
        path = ROOT / 'diagnostics/rooms_auto_v1' / ('public_gui.json' if args.public_url else 'worker_gui.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
