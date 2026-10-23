"""Real sockets, room authorization, TLS and emulator-protocol bridge tests."""
import asyncio
import secrets
import socket
import ssl
import struct
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest

from lobby_server import Directory
from relay_client import RelayBridge, open_tunnel
from relay_protocol import (CONTROL, FRAME, MAGIC, endpoint, issue_ticket,
                            read_frame, verify_ticket, write_frame)
from relay_server import Relay

SECRET = "local-test-only-" + "a" * 48


class TicketsTest(unittest.TestCase):
    def test_signature_expiry_side_and_session(self):
        token = issue_ticket(SECRET, "a" * 48, 0, now=1000)
        self.assertEqual(verify_ticket(SECRET, token, now=1001)["side"], 0)
        for bad in (token[:-1] + "x", "", "a.b.c", "a.b", None):
            with self.assertRaises(ValueError):
                verify_ticket(SECRET, bad, now=1001)
        for now in (1090, 900):
            with self.assertRaises(ValueError):
                verify_ticket(SECRET, token, now=now)
        for session, side in (("a", 0), ("b" * 48, 2), ("c" * 48, True)):
            with self.assertRaises(ValueError):
                verify_ticket(SECRET, issue_ticket(SECRET, session, side, now=1000), now=1001)
        with self.assertRaises(ValueError):
            verify_ticket("b" * 48, token, now=1001)

    def test_internet_requires_tls_and_rejects_injection(self):
        for url in ("http://example.com/tm3-relay", "https://u:p@example.com/tm3-relay",
                    "https://example.com/tm3-relay?x=y", "https://example.com/\r\nBad:x",
                    "https://example.com/wrong", "https://example.com:70000/tm3-relay"):
            with self.assertRaises(ValueError):
                endpoint(url)
        self.assertEqual(endpoint("https://lobby.example/tm3-relay")[1], 443)
        self.assertFalse(endpoint("http://127.0.0.1:27900/tm3-relay")[3])

    def test_directory_ticket_privacy_capability_and_generation(self):
        directory = Directory(":memory:", "https://lobby.example/tm3-relay", SECRET)
        try:
            def login(name, capability=1):
                return directory.request(dict(op="login", name=name, secret=secrets.token_hex(32),
                                              relay_protocol=capability), "100.64.0.1")["token"]
            def op(token, name, **kwargs):
                return directory.request(dict(token=token, op=name, **kwargs), "100.64.0.1")
            host, guest, observer = login("Host"), login("Guest", 0), login("Observer")
            room = op(host, "create")["room"]
            op(guest, "join", room=room["id"])
            with self.assertRaisesRegex(ValueError, "Actualiza"):
                op(host, "start")
            directory.sessions[guest]["relay_protocol"] = 1
            state = op(host, "start")["room"]
            host_claims = verify_ticket(SECRET, state["transport"]["ticket"])
            guest_claims = verify_ticket(SECRET, op(guest, "poll")["room"]["transport"]["ticket"])
            self.assertEqual(host_claims["session"], guest_claims["session"])
            self.assertEqual((host_claims["side"], guest_claims["side"]), (0, 1))
            self.assertIsNone(op(observer, "poll")["rooms"][0]["transport"])
            op(guest, "cancel", generation=state["generation"])
            state2 = op(host, "start")["room"]
            self.assertNotEqual(host_claims["session"], verify_ticket(SECRET, state2["transport"]["ticket"])["session"])
        finally:
            directory.db.close()


class RelaySocketsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.relay = Relay(SECRET, pair_timeout=.5)
        self.server = await asyncio.start_server(self.relay.accept, "127.0.0.1", 0, limit=8192)
        self.port = self.server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/tm3-relay"
        self.writers = []
        self.bridges = []

    async def asyncTearDown(self):
        await asyncio.gather(*(asyncio.to_thread(b.close) for b in self.bridges))
        for writer in self.writers:
            writer.close()
        await self.relay.close()
        self.server.close()
        await self.server.wait_closed()
        self.assertEqual(self.relay.connections, 0)
        self.assertFalse(self.relay.rooms)

    async def tunnel(self, session, side):
        reader, writer = await open_tunnel(self.url, issue_ticket(SECRET, session, side))
        self.writers.append(writer)
        return reader, writer

    async def test_pairing_isolation_datagrams_and_control(self):
        ar, aw = await self.tunnel("a" * 48, 0)
        br, bw = await self.tunnel("b" * 48, 0)
        cr, cw = await self.tunnel("a" * 48, 1)
        dr, dw = await self.tunnel("b" * 48, 1)
        control = CONTROL.pack(MAGIC, 7, 5, 0, 0, 123)
        await write_frame(aw, b"C", control)
        self.assertEqual(await read_frame(cr, 1), (b"C", control))
        payload = b"TM3O" + bytes(48) + b"isolated"
        await write_frame(dw, b"D", payload)
        self.assertEqual(await read_frame(br, 1), (b"D", payload))
        # If the relay leaked the previous room's data, this read sees it first.
        await write_frame(bw, b"P")
        self.assertEqual(await read_frame(br, 1), (b"P", b""))

    async def test_duplicate_seat_does_not_disconnect_valid_peer(self):
        ar, aw = await self.tunnel("a" * 48, 0)
        with self.assertRaises(asyncio.IncompleteReadError):
            await self.tunnel("a" * 48, 0)
        br, bw = await self.tunnel("a" * 48, 1)
        await write_frame(aw, b"P")
        self.assertEqual(await read_frame(ar, 1), (b"P", b""))

    async def test_invalid_ticket_rejected(self):
        with self.assertRaises(asyncio.IncompleteReadError):
            await open_tunnel(self.url, issue_ticket("x" * 48, "a" * 48, 0))

    async def test_invalid_and_oversize_frames_close_both_seats(self):
        for bad in (FRAME.pack(b"D", 4097), FRAME.pack(b"C", 1) + b"x"):
            session = secrets.token_hex(24)
            ar, aw = await self.tunnel(session, 0)
            br, bw = await self.tunnel(session, 1)
            aw.write(bad)
            await aw.drain()
            self.assertEqual(await asyncio.wait_for(br.read(), 1), b"")

    async def test_pair_timeout_reclaims_seat(self):
        ar, aw = await self.tunnel("a" * 48, 0)
        self.assertEqual(await asyncio.wait_for(ar.read(), 1), b"")

    async def test_connection_limit(self):
        self.relay.max_connections = 1
        await self.tunnel("a" * 48, 0)
        with self.assertRaises((ConnectionError, asyncio.IncompleteReadError)):
            await self.tunnel("b" * 48, 0)

    async def test_disconnect_propagates(self):
        ar, aw = await self.tunnel("a" * 48, 0)
        br, bw = await self.tunnel("a" * 48, 1)
        aw.close()
        self.assertEqual(await asyncio.wait_for(br.read(), 1), b"")

    async def test_tls_trust_and_hostname_validation(self):
        openssl = shutil.which("openssl")
        if not openssl:
            candidate = Path("C:/Program Files/Git/usr/bin/openssl.exe")
            openssl = str(candidate) if candidate.is_file() else None
        if not openssl:
            self.skipTest("OpenSSL CLI required to generate an ephemeral test certificate")
        with tempfile.TemporaryDirectory(prefix="tm3_tls_qa_") as folder:
            cert, key = Path(folder) / "cert.pem", Path(folder) / "key.pem"
            await asyncio.to_thread(subprocess.run, [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=TM3RelayQA",
                "-addext", "subjectAltName=IP:127.0.0.1"], check=True, capture_output=True)
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(cert, key)
            server = await asyncio.start_server(self.relay.accept, "127.0.0.1", 0, ssl=server_context, limit=8192)
            port = server.sockets[0].getsockname()[1]
            url = f"https://127.0.0.1:{port}/tm3-relay"
            ticket = issue_ticket(SECRET, "a" * 48, 0)
            try:
                with self.assertRaises(ssl.SSLCertVerificationError):
                    await open_tunnel(url, ticket)
                trusted = ssl.create_default_context(cafile=str(cert))
                with self.assertRaises(ssl.SSLCertVerificationError):
                    await open_tunnel(f"https://localhost:{port}/tm3-relay", ticket, trusted)
                with self.assertRaises(ValueError):
                    await open_tunnel(url, ticket, ssl._create_unverified_context())
                ar, aw = await open_tunnel(url, ticket, trusted)
                br, bw = await open_tunnel(url, issue_ticket(SECRET, "a" * 48, 1), trusted)
                self.writers += [aw, bw]
                cancel = CONTROL.pack(MAGIC, 7, 5, 0, 0, 42)
                await write_frame(aw, b"C", cancel)
                self.assertEqual(await read_frame(br, 1), (b"C", cancel))
            finally:
                for writer in self.writers:
                    writer.close()
                await self.relay.close()
                server.close()
                await server.wait_closed()

    async def test_close_bridge_while_waiting_for_emulator(self):
        self.relay.pair_timeout = 5
        bridge = RelayBridge(dict(protocol=1, url=self.url,
                            ticket=issue_ticket(SECRET, "a" * 48, 1)))
        self.bridges.append(bridge)
        await asyncio.to_thread(bridge.start)
        await asyncio.to_thread(bridge.close)
        self.assertTrue(bridge.done.is_set())
        self.assertFalse(bridge.thread.is_alive())
        self.assertFalse(bridge.error)

    async def test_emulator_handshake_udp_and_cancel_through_bridges(self):
        # Two independent UDP endpoints and two real TCP endpoints speak the
        # unmodified protocol 7; neither emulator connects to a remote peer.
        loop = asyncio.get_running_loop()
        host_tcp = loop.create_future()
        async def accept(reader, writer):
            host_tcp.set_result((reader, writer))
        host_server = await asyncio.start_server(accept, "127.0.0.1", 0)
        host_port = host_server.sockets[0].getsockname()[1]
        session = secrets.token_hex(24)
        self.relay.pair_timeout = 5
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as hu, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as gu:
            hu.bind(("127.0.0.1", 0)); gu.bind(("127.0.0.1", 0))
            hu.setblocking(False); gu.setblocking(False)
            try:
                def make(side, port=None):
                    bridge = RelayBridge(dict(protocol=1, url=self.url,
                        ticket=issue_ticket(SECRET, session, side)), host_port=port)
                    self.bridges.append(bridge)
                    return bridge
                host, guest = make(0, host_port), make(1)
                await asyncio.to_thread(host.start)
                await asyncio.to_thread(guest.start)
                hr, hw = await asyncio.wait_for(host_tcp, 2)
                gr, gw = await asyncio.open_connection("127.0.0.1", guest.local_port)
                self.writers += [hw, gw]
                gw.write(CONTROL.pack(MAGIC, 7, 1, gu.getsockname()[1], 0, 0))
                hello = CONTROL.unpack(await asyncio.wait_for(hr.readexactly(24), 2))
                self.assertNotEqual(hello[3], gu.getsockname()[1])
                hw.write(CONTROL.pack(MAGIC, 7, 2, hu.getsockname()[1], 0, 42))
                accepted = CONTROL.unpack(await asyncio.wait_for(gr.readexactly(24), 2))
                self.assertNotEqual(accepted[3], hu.getsockname()[1])
                for sock, port, other, message in ((gu, accepted[3], hu, b"guest"), (hu, hello[3], gu, b"host")):
                    data = b"TM3O" + bytes(48) + message
                    await loop.sock_sendto(sock, data, ("127.0.0.1", port))
                    received, address = await asyncio.wait_for(loop.sock_recvfrom(other, 2048), 2)
                    self.assertEqual(received, data)
                cancel = CONTROL.pack(MAGIC, 7, 5, 0, 0, 42)
                gw.write(cancel)
                self.assertEqual(await asyncio.wait_for(hr.readexactly(24), 2), cancel)
                self.assertFalse(host.done.is_set())
                self.assertFalse(guest.done.is_set())
                # Unknown local UDP sources cannot inject traffic into the tunnel.
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stranger:
                    stranger.sendto(b"TM3O" + bytes(48), ("127.0.0.1", hello[3]))
                await asyncio.sleep(.05)
                self.assertEqual(host.sent, 1)
                await asyncio.to_thread(guest.close)
                self.assertEqual(await asyncio.wait_for(hr.read(), 2), b"")
            finally:
                if host_tcp.done():
                    host_tcp.result()[1].close()
                host_server.close()
                await host_server.wait_closed()


if __name__ == "__main__":
    unittest.main()
