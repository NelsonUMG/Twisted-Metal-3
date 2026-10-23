"""Packaged QA: automatic signaling via Worker + actual local game sockets."""
import secrets
import socket
import time

from worker_directory import WorkerDirectory
from p2p_session import P2PSession
from relay_protocol import CONTROL, MAGIC


def run_check(url):
    clients, peers, tokens = [], [], []
    def call(index, op, **kwargs):
        time.sleep(.15)
        return clients[index].request(dict(op=op, token=tokens[index], **kwargs))
    try:
        for role in ('Host', 'Guest', 'Observer'):
            client = WorkerDirectory(url)
            clients.append(client)
            tokens.append(client.request(dict(op='login', name=role + ' ' + secrets.token_hex(4), automatic_ice=1))['token'])
        rid = call(0, 'create', description='Frozen QA automatic room')['room']['id']
        assert any(r['id'] == rid for r in call(1, 'poll')['rooms'])
        call(1, 'join', room=rid)
        generation = call(0, 'start')['room']['generation']
        host, guest = P2PSession(ice_servers=[]), P2PSession(ice_servers=[])
        peers.extend((host, guest))
        call(0, 'ice_offer', generation=generation, code=host.create_offer())
        assert all(r['transport'] is None for r in call(2, 'poll')['rooms'])
        offer = call(1, 'poll')['room']['transport']['offer']
        call(1, 'ice_answer', generation=generation, code=guest.create_answer(offer))
        host.accept_answer(call(0, 'poll')['room']['transport']['answer'])
        assert host.connected.wait(8) and guest.connected.wait(8)
        call(0, 'ice_ready', generation=generation)
        assert call(1, 'ice_ready', generation=generation)['room']['phase'] == 'prepare'
        with socket.socket() as listen, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as hu, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as gu:
            listen.bind(('127.0.0.1', 0)); listen.listen(1); listen.settimeout(3)
            hu.bind(('127.0.0.1', 0)); gu.bind(('127.0.0.1', 0))
            hu.settimeout(3); gu.settimeout(3)
            host.attach_game(listen.getsockname()[1], generation=generation)
            hr, _ = listen.accept()
            gr = socket.create_connection(('127.0.0.1', guest.attach_game(generation=generation)), timeout=3)
            try:
                hr.settimeout(3)
                gr.sendall(CONTROL.pack(MAGIC, 7, 1, gu.getsockname()[1], 0, 0))
                hello = CONTROL.unpack(hr.recv(24))
                hr.sendall(CONTROL.pack(MAGIC, 7, 2, hu.getsockname()[1], 0, 42))
                accepted = CONTROL.unpack(gr.recv(24))
                for sock, port, other in ((hu, hello[3], gu), (gu, accepted[3], hu)):
                    payload = b'TM3O' + bytes(48) + b'AUTO-ROOM-FROZEN'
                    sock.sendto(payload, ('127.0.0.1', port))
                    assert other.recv(2048) == payload
                cancel = CONTROL.pack(MAGIC, 7, 5, 0, 0, 42)
                gr.sendall(cancel)
                assert hr.recv(24) == cancel
            finally:
                hr.close(); gr.close()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and not all(p.latency_snapshot()['samples'] for p in peers):
            time.sleep(.02)
        assert all(p.latency_snapshot()['samples'] and not p.latency_snapshot()['stale'] for p in peers)
        return dict(passed=True, automatic_worker_signaling=True, room_list=True,
                    private_signaling=True, manual_codes_used=False,
                    encrypted_ice=True, native_controls_and_datagrams=True,
                    peer_ping_measured=True, diagnostics=host.snapshot())
    finally:
        for peer in peers:
            peer.close()
        for index, client in enumerate(clients):
            try:
                if index < len(tokens):
                    call(index, 'logout')
            except Exception:
                pass
            finally:
                client.close()
