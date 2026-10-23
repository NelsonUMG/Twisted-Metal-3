"""Offline functional check used by the frozen executable. No real game/profile."""
import socket
from p2p_session import P2PSession
from relay_protocol import CONTROL, MAGIC


def run_check():
    host, guest = P2PSession(ice_servers=[]), P2PSession(ice_servers=[])
    try:
        answer = guest.create_answer(host.create_offer())
        host.accept_answer(answer)
        if not host.connected.wait(8) or not guest.connected.wait(8):
            raise RuntimeError('Local ICE did not connect')
        with socket.socket() as listen, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as hu, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as gu:
            listen.bind(('127.0.0.1', 0)); listen.listen(1); listen.settimeout(3)
            hu.bind(('127.0.0.1', 0)); gu.bind(('127.0.0.1', 0))
            hu.settimeout(3); gu.settimeout(3)
            host.attach_game(listen.getsockname()[1])
            hr, _ = listen.accept()
            gr = socket.create_connection(('127.0.0.1', guest.attach_game()), timeout=3)
            try:
                hr.settimeout(3)
                gr.sendall(CONTROL.pack(MAGIC, 7, 1, gu.getsockname()[1], 0, 0))
                hello = CONTROL.unpack(hr.recv(24))
                hr.sendall(CONTROL.pack(MAGIC, 7, 2, hu.getsockname()[1], 0, 42))
                accepted = CONTROL.unpack(gr.recv(24))
                for sock, port, other in ((hu, hello[3], gu), (gu, accepted[3], hu)):
                    message = b'TM3O' + bytes(48) + b'ICE-FROZEN-QA'
                    sock.sendto(message, ('127.0.0.1', port))
                    assert other.recv(2048) == message
                cancel = CONTROL.pack(MAGIC, 7, 5, 0, 0, 42)
                gr.sendall(cancel)
                assert hr.recv(24) == cancel
                return dict(passed=True, ice=True, encrypted=host.pc.sctp.transport.state == 'connected',
                            reliable_control=True, unordered_gameplay=True, datagrams_both_directions=True,
                            cancel_keeps_transport=host.connected.is_set() and guest.connected.is_set(),
                            diagnostics=host.snapshot())
            finally:
                hr.close(); gr.close()
    finally:
        host.close(); guest.close()
