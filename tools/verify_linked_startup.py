"""Real two-emulator startup, cancellation and process-exit check on loopback."""
from pathlib import Path
import ctypes
import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import threading

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'network'))
from lobby_client import Lobby, listening
from relay_server import Relay
from relay_client import RelayBridge
from relay_protocol import issue_ticket


class TestRelay:
    """Owned loopback relay; never starts a public service or opens firewall rules."""
    def __init__(self):
        self.ready = threading.Event()
        self.secret = secrets.token_hex(32)
        self.session = secrets.token_hex(24)
        self.bridges = []
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        assert self.ready.wait(5), 'Test relay did not start'

    def run(self):
        async def serve():
            self.loop = asyncio.get_running_loop()
            self.stop = asyncio.Event()
            relay = Relay(self.secret)
            server = await asyncio.start_server(relay.accept, '127.0.0.1', 0, limit=8192)
            self.port = server.sockets[0].getsockname()[1]
            self.ready.set()
            try:
                await self.stop.wait()
            finally:
                await relay.close()
                server.close()
                await server.wait_closed()
        asyncio.run(serve())

    def bridge(self, side, host_port=None):
        bridge = RelayBridge(dict(protocol=1, url=f'http://127.0.0.1:{self.port}/tm3-relay',
            ticket=issue_ticket(self.secret, self.session, side)), host_port=host_port)
        self.bridges.append(bridge)
        bridge.start()
        return bridge

    def close(self):
        for bridge in self.bridges:
            bridge.close()
        self.loop.call_soon_threadsafe(self.stop.set)
        self.thread.join(timeout=5)
        assert not self.thread.is_alive(), 'Test relay thread leaked'

def wait_for(predicate, timeout, message):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate(): return
        time.sleep(.05)
    raise RuntimeError(message() if callable(message) else message)

def read(path):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return {}

def main():
    processes, handles = [], []
    relay = TestRelay() if '--relay' in sys.argv else None
    closer = Lobby.__new__(Lobby)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    env = {k:v for k,v in os.environ.items() if not k.startswith('TM3O_')}
    env.update(TM3O_LINK_HIRES_WAIT='1', TM3O_LINK_UDP_WAKE='1', TM3O_DIAGNOSTICS='0')
    with tempfile.TemporaryDirectory(prefix='tm3_linked_qa_') as directory:
        base = Path(directory)
        try:
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
            states = []
            for name, mode in (('host', ['--host', str(port)]), ('guest', ['--join', f'127.0.0.1:{port}'])):
                if relay and name == 'guest':
                    guest_bridge = relay.bridge(1)
                    mode = ['--join', f'127.0.0.1:{guest_bridge.local_port}']
                folder = base / name; folder.mkdir()
                exe = folder / 'TM3Online.exe'
                shutil.copy2(ROOT / 'diagnostics/lobby_console_v1/build/Release/TM3Online.exe', exe)
                two_local = '--two-local-players' in sys.argv
                (folder / 'TM3Console.ini').write_text('[Console]\nMuted=1\nPlayer2Enabled=' + ('1' if two_local else '0') + '\n', encoding='utf-8')
                state = folder / 'session.json'; states.append(state)
                event_name = 'Local\\TM3QA_' + secrets.token_hex(16)
                create = ctypes.windll.kernel32.CreateEventW; create.restype = ctypes.c_void_p
                handle = create(None, True, False, event_name); assert handle
                handles.append(handle)
                process = subprocess.Popen([str(exe), '--windowed', '--core', str(ROOT / 'TM3Online_Lobby/runtime/cores/beetle_psx_libretro.dll'),
                    '--game', str(ROOT / 'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.cue'),
                    '--parent-pid', str(os.getpid()), '--session-state', str(state), '--return-menu-event', event_name, *mode],
                    env=env, startupinfo=startup, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                processes.append(process)
                if name == 'host':
                    wait_for(lambda: listening(process.pid, port), 8, 'Host did not listen')
                    if relay:
                        relay.bridge(0, port)
            wait_for(lambda: all(read(p).get('state') == 'connected' for p in states), 25,
                     lambda: f'Guest mailbox did not confirm connection; states={[read(p) for p in states]}; exits={[p.poll() for p in processes]}')
            print('PASS: both actual game mailboxes confirm the linked connection, protocol 7.', flush=True)
            if relay:
                assert all(not b.error for b in relay.bridges)
                print('PASS: both actual emulators connect through relay bridges; no direct peer TCP connection.', flush=True)
            assert all(read(p).get('player2_enabled') == two_local for p in states)
            print(f'PASS: second controller port enabled={two_local} on both actual emulators.', flush=True)
            ctypes.windll.kernel32.SetEvent(ctypes.c_void_p(handles[1]))
            wait_for(lambda: all(read(p).get('state') == 'returned' for p in states), 12,
                     'Guest cancellation did not return both real emulators')
            assert all(p.poll() is None for p in processes)
            assert all(read(p).get('transport_connected') and read(p).get('guest_ready') for p in states), 'Return to main menu disconnected online play'
            print('PASS: guest cancellation returns both loaded games; emulator windows remain alive.', flush=True)
            for process in processes:
                closer.close_process(process)
                assert process.poll() == 0, f'Emulator required forced close: {process.returncode}'
            print('PASS: both real emulators close gracefully; no owned game process remains.', flush=True)
            helper_code = '''import os,subprocess,sys
startup=subprocess.STARTUPINFO()
startup.dwFlags=subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow=0
p=subprocess.Popen([sys.argv[1], '--empty', '--parent-pid', str(os.getpid())], startupinfo=startup)
print(p.pid,flush=True)
sys.stdin.readline()
'''
            helper = subprocess.Popen([sys.executable, '-c', helper_code, str(base/'host/TM3Online.exe')],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            child_pid = int(helper.stdout.readline())
            open_process = ctypes.windll.kernel32.OpenProcess; open_process.restype = ctypes.c_void_p
            child_handle = open_process(0x100001, False, child_pid)
            assert child_handle
            try:
                time.sleep(.5)
                helper.terminate();helper.wait(timeout=3)
                exited = ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(child_handle), 8000) == 0
                if not exited: ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(child_handle), 1)
                assert exited, 'Game did not exit after its lobby parent disappeared'
            finally:
                if helper.poll() is None: helper.terminate();helper.wait(timeout=3)
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(child_handle))
            print('PASS: actual emulator exits when its owning parent process disappears.', flush=True)
        finally:
            for process in processes:
                closer.close_process(process)
            if relay:
                relay.close()
            for handle in handles:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))

if __name__ == '__main__': main()
