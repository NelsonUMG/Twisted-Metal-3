"""Unmodified C++ NetBridge fixture over ICE/DTLS/SCTP with manual signaling."""
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'network'))
from p2p_session import P2PSession
from lobby_client import listening
from verify_linked_startup import wait_for


def main():
    host, guest = P2PSession(ice_servers=[]), P2PSession(ice_servers=[])
    process = None
    try:
        guest_answer = guest.create_answer(host.create_offer())
        host.accept_answer(guest_answer)
        assert host.connected.wait(8) and guest.connected.wait(8)
        guest_port = guest.attach_game()
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        env = {k:v for k,v in os.environ.items() if not k.startswith('TM3O_')}
        env.update(TM3_QA_HOST_PORT=str(port), TM3_QA_JOIN_PORT=str(guest_port),
                   TM3O_LINK_HIRES_WAIT='1', TM3O_LINK_UDP_WAKE='1')
        process = subprocess.Popen([str(ROOT/'diagnostics/lobby_console_v1/build/Release/TM3NetRelayTest.exe')],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        wait_for(lambda: listening(process.pid, port) or process.poll() is not None, 5, 'Fixture did not listen')
        host.attach_game(port)
        output, _ = process.communicate(timeout=40)
        print(output, end='')
        assert process.returncode == 0, f'C++ ICE test exit={process.returncode}'
        assert host.sent and guest.sent and host.received and guest.received
        print(f'PASS: real ICE/DTLS/SCTP path, control reliable, game unordered/unreliable; datagrams={host.sent}/{guest.sent}')
    finally:
        if process and process.poll() is None:
            process.terminate(); process.wait(timeout=3)
        host.close(); guest.close()


if __name__ == '__main__':
    main()
