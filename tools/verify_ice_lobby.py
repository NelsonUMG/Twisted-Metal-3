"""Manual-code GUI workflow + two real emulators, temporary profiles, no WAN."""
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'network'))
from lobby_client import Lobby


def main():
    apps = []
    report = {}
    simulated = '--simulated-nat' in sys.argv
    spawn = subprocess.Popen
    def hidden_spawn(*args, **kwargs):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        kwargs['startupinfo'] = startup
        return spawn(*args, **kwargs)
    def wait(predicate, seconds, label):
        deadline = time.monotonic() + seconds
        while True:
            for app in apps:
                app.root.update()
            if predicate():
                return
            if time.monotonic() > deadline:
                raise RuntimeError(label + ': ' + str([(a.p2p_window.status.cget('text'), a.session_state()) for a in apps]))
            time.sleep(.02)
    with ExitStack() as stack:
        if simulated:
            from ice_nat_lab import NatNetwork, SimulatedP2PSession, isolated_ice_addresses
            network = NatNetwork()
            sim_sides = iter((0, 1))
            stack.enter_context(isolated_ice_addresses())
            stack.enter_context(patch('p2p_window.P2PSession',
                new=lambda ice_servers: SimulatedP2PSession(network, next(sim_sides))))
            report.update(simulated_nat=True, real_wan_test=False, real_hotspot_test=False)
        folder = stack.enter_context(tempfile.TemporaryDirectory(prefix='tm3_ice_lobby_qa_'))
        stack.enter_context(patch('lobby_client.subprocess.Popen', new=hidden_spawn))
        base = Path(folder)
        try:
            for i in range(2):
                side = base/str(i)
                side.mkdir()
                exe = side/'TM3Online.exe'
                shutil.copy2(ROOT/'TM3Online_Lobby/runtime/TM3Online.exe', exe)
                (side/'TM3Console.ini').write_text('[Console]\nMuted=1\nPlayer2Enabled=1\n', encoding='utf-8')
                root = tk.Tk(); root.withdraw()
                with patch('lobby_client.DATA', side), patch('lobby_client.load_config', return_value={}):
                    app = Lobby(root)
                apps.append(app)
                for timer in root.tk.call('after', 'info'):
                    root.after_cancel(timer)
                app.config = dict(p2p=dict(ice_servers=[]), runtime=dict(executable=str(exe),
                    core=str(ROOT/'TM3Online_Lobby/runtime/cores/beetle_psx_libretro.dll'),
                    game=str(ROOT/'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.cue'),
                    environment=dict(TM3O_LINK_HIRES_WAIT='1', TM3O_LINK_UDP_WAKE='1', TM3O_CPU_BUDGET_PERCENT='175')))
                with patch('lobby_client.DATA', side):
                    app.open_p2p()
                app.p2p_window.window.withdraw()
            with patch('lobby_client.DATA', base):
                host, guest = [a.p2p_window for a in apps]
                host.offer()
                wait(lambda: host.output.get('1.0', 'end').strip(), 10, 'Host offer missing')
                guest.input.insert('1.0', host.output.get('1.0', 'end').strip())
                guest.answer()
                wait(lambda: guest.output.get('1.0', 'end').strip(), 10, 'Guest answer missing')
                host.input.insert('1.0', guest.output.get('1.0', 'end').strip())
                host.accept()
                wait(lambda: all(w.peer.connected.is_set() and w.game for w in (host, guest)), 10, 'ICE not connected')
                report['manual_code_ice_connected'] = True
                host.start_game()
                def games_connected():
                    return all(a.session_state().get('state') == 'connected' for a in apps)
                wait(games_connected, 40, 'First startup failed')
                assert all(a.session_state().get('player2_enabled') for a in apps)
                report['actual_emulators_connected'] = report['second_controller_enabled'] = True
                guest.owner.return_room_process()
                wait(lambda: all(a.session_state().get('state') == 'returned' for a in apps), 15, 'Cancel failed')
                wait(lambda: host.game.state == guest.game.state == 'waiting', 5, 'Controller did not return to waiting')
                assert all(a.session_state().get('transport_connected') for a in apps)
                assert host.peer.connected.is_set() and guest.peer.connected.is_set()
                report['cancel_preserves_transport'] = True
                host.start_game()
                wait(lambda: host.game.generation == guest.game.generation == 2 and games_connected(), 40, 'Second startup failed')
                report['second_start_new_generation'] = True
                report['diagnostics'] = host.peer.snapshot()
                if simulated:
                    from ice_nat_lab import PUBLIC_IPS
                    report['selected_paths'] = [w.peer.selected_path() for w in (host, guest)]
                    assert all(path[0]['remote'][0] == PUBLIC_IPS[1 - i]
                               for i, path in enumerate(report['selected_paths']))
                for app in apps:
                    app.close()
                report['owned_processes_closed'] = all(a.process is None and a.p2p_window is None for a in apps)
                apps.clear()
        finally:
            for app in apps:
                app.close()
        if simulated:
            report['network'] = network.snapshot()
    name = 'lobby_nat_check.json' if simulated else 'lobby_check.json'
    path = ROOT/'diagnostics/ice_p2p_v1'/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
