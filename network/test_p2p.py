import asyncio
import base64
import json
import socket
import struct
import threading
import time
import unittest
import zlib
from unittest.mock import patch

from p2p_codes import PREFIX, decode_description
from p2p_session import DatagramOutbox, LatencyTracker, P2PSession
from relay_protocol import CONTROL, MAGIC


class LatencyTest(unittest.TestCase):
    def test_rtt_and_window_statistics_use_local_monotonic_time(self):
        tracker = LatencyTracker()
        for i, ms in enumerate((40, 60, 50)):
            sent = (i + 1) * 2_000_000_000
            self.assertEqual(tracker.probe(sent), b'P' + struct.pack('!Q', sent))
            self.assertTrue(tracker.echo(sent, sent + ms * 1_000_000))
        stats = tracker.summary()
        self.assertEqual(stats['rtt_ms'], 50)
        self.assertEqual(stats['average_ms'], 50)
        self.assertEqual(stats['minimum_ms'], 40)
        self.assertEqual(stats['maximum_ms'], 60)
        self.assertEqual(stats['variation_ms'], 15)
        self.assertEqual(stats['samples'], 3)

    def test_unknown_duplicate_future_and_expired_echoes_do_not_count(self):
        tracker = LatencyTracker()
        self.assertFalse(tracker.echo(1, 20))
        tracker.probe(100)
        self.assertTrue(tracker.echo(100, 200))
        self.assertFalse(tracker.echo(100, 300))
        tracker.probe(500)
        self.assertFalse(tracker.echo(500, 400))
        tracker.probe(600)
        self.assertFalse(tracker.echo(600, 10_000_000_601))
        self.assertEqual(tracker.summary()['samples'], 1)

    def test_pending_probes_and_sample_history_are_bounded(self):
        tracker = LatencyTracker()
        for i in range(100):
            tracker.probe(i)
        self.assertLessEqual(len(tracker.pending), 8)
        for i in range(100, 200):
            tracker.probe(i)
            self.assertTrue(tracker.echo(i, i + 1))
        self.assertEqual(tracker.summary()['samples'], 30)
        self.assertEqual(tracker.samples.maxlen, 30)
        tracker.probe(11_000_000_000)
        self.assertEqual(len(tracker.pending), 1)

    def test_ui_snapshot_is_nonblocking_and_marks_stale_or_disconnected(self):
        peer = P2PSession.__new__(P2PSession)
        peer.connected, peer.done = threading.Event(), threading.Event()
        peer.connected.set()
        tracker = LatencyTracker()
        tracker.probe(1_000_000_000)
        tracker.echo(1_000_000_000, 1_040_000_000)
        peer._latency_view = (tracker.summary(), tracker.last_sample_ns)
        with patch('p2p_session.time.monotonic_ns', return_value=2_040_000_000):
            self.assertFalse(peer.latency_snapshot()['stale'])
            self.assertEqual(peer.latency_snapshot()['age_seconds'], 1)
        with patch('p2p_session.time.monotonic_ns', return_value=7_040_000_000):
            self.assertTrue(peer.latency_snapshot()['stale'])
        peer.done.set()
        self.assertFalse(peer.latency_snapshot()['connected'])
        self.assertTrue(peer.latency_snapshot()['stale'])


class OutboxTest(unittest.TestCase):
    def test_first_send_immediate_exact_retry_coalesced_then_allowed(self):
        outbox = DatagramOutbox()
        self.assertTrue(outbox.offer(b'frame', 1, 10, .05))
        self.assertTrue(outbox.offer(b'frame', 1, 10.008, .05))
        self.assertEqual(len(outbox.pending), 1)
        self.assertEqual(outbox.pop(1, 10.01), b'\0\0\0\1frame')
        self.assertTrue(outbox.offer(b'frame', 1, 10.02, .05))
        self.assertFalse(outbox.pending)
        self.assertTrue(outbox.offer(b'frame', 1, 10.07, .05))
        self.assertEqual(len(outbox.pending), 1)
        self.assertEqual(outbox.coalesced, 2)

    def test_fragments_fifo_distinct_payload_and_generation_not_coalesced(self):
        outbox = DatagramOutbox()
        for data in (b'first', b'second', b'third'):
            outbox.offer(data, 1, 10, .05)
        outbox.offer(b'first', 1, 10.008, .05)
        self.assertEqual([outbox.pop(1, 10.02)[4:] for _ in range(3)], [b'first', b'second', b'third'])
        outbox.offer(b'first', 2, 10.03, .05)
        self.assertEqual(outbox.pop(2, 10.04), b'\0\0\0\2first')

    def test_queue_history_and_lifetime_bounded(self):
        outbox = DatagramOutbox()
        for i in range(256):
            self.assertTrue(outbox.offer(str(i).encode(), 1, 10, .05))
        self.assertFalse(outbox.offer(b'overflow', 1, 10, .05))
        self.assertTrue(outbox.offer(b'0', 1, 10, .05))
        self.assertIsNone(outbox.pop(1, 12))
        self.assertEqual(outbox.expired, 256)
        for i in range(700):
            outbox.offer(str(i).encode(), 1, 20, .05)
            outbox.pop(1, 20)
        self.assertEqual(len(outbox.history), 512)

    def test_retired_generation_never_sent_and_clear_releases_history(self):
        outbox = DatagramOutbox()
        outbox.offer(b'old', 1, 10, .05)
        outbox.offer(b'new', 2, 10, .05)
        self.assertEqual(outbox.pop(2, 10.01), b'\0\0\0\2new')
        self.assertEqual(outbox.expired, 1)
        outbox.clear()
        self.assertFalse(outbox.history)
        self.assertFalse(outbox.pending)


class PeerTest(unittest.TestCase):
    def setUp(self):
        self.host = P2PSession(ice_servers=[])
        self.guest = P2PSession(ice_servers=[])

    def tearDown(self):
        self.host.close()
        self.guest.close()
        self.assertFalse(self.host.thread.is_alive())
        self.assertFalse(self.guest.thread.is_alive())

    def pair(self):
        offer = self.host.create_offer()
        answer = self.guest.create_answer(offer)
        self.host.accept_answer(answer)
        self.assertTrue(self.host.connected.wait(8), self.host.error)
        self.assertTrue(self.guest.connected.wait(8), self.guest.error)
        return offer, answer

    def test_ice_dtls_and_two_channel_modes(self):
        self.pair()
        self.assertTrue(self.host.control.ordered)
        self.assertIsNone(self.host.control.maxRetransmits)
        self.assertFalse(self.host.data.ordered)
        self.assertEqual(self.host.data.maxRetransmits, 0)
        self.assertIn(self.host.snapshot()['selected'].get('local_type'), ('host', 'srflx', 'prflx'))
        self.host.send_message(dict(op='chat', text='Hola 🎮'))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            event, data = self.guest.events.get(timeout=3)
            if event == 'message':
                self.assertEqual(data, dict(op='chat', text='Hola 🎮'))
                break
        else:
            self.fail('Peer message did not arrive')
        text = json.dumps(self.host.snapshot())
        self.assertNotIn('ice-pwd', text)
        self.assertNotIn('fingerprint:', text)
        self.host.close()
        saved = self.host.snapshot()
        self.assertTrue(saved['closed'])
        self.assertTrue(saved['candidates'].get('host'))

    def test_peer_ping_samples_without_game_or_directory_and_close_stales_them(self):
        self.pair()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and not all(p.latency_snapshot()['samples'] for p in (self.host, self.guest)):
            time.sleep(.02)
        for peer in (self.host, self.guest):
            stats = peer.latency_snapshot()
            self.assertGreater(stats['samples'], 0)
            self.assertGreaterEqual(stats['rtt_ms'], 0)
            self.assertFalse(stats['stale'])
            self.assertEqual(peer.snapshot()['latency']['method'], 'encrypted_control_echo')
        self.host.close()
        self.assertFalse(self.host.latency_snapshot()['connected'])
        self.assertTrue(self.host.snapshot()['latency']['stale'])

    def test_invitation_validation_and_wrong_session(self):
        offer = self.host.create_offer()
        answer = self.guest.create_answer(offer)
        value = decode_description(offer, 'offer')
        for bad in ('bad', offer[:-5], 'x' * 32001, answer):
            with self.assertRaises(ValueError):
                decode_description(bad, 'offer')
        for offset in (-86400, -780, 780, 86400):
            self.assertEqual(decode_description(offer, 'offer', now=value['expires'] + offset)['session'], value['session'])
        with self.assertRaises(ValueError):
            decode_description(answer, 'answer', session='a' * 32)
        self.assertEqual(decode_description('\n' + offer[:60] + '\n' + offer[60:], 'offer')['session'], value['session'])
        bomb = PREFIX + base64.urlsafe_b64encode(zlib.compress(b'x' * 1000000)).decode()
        with self.assertRaises(ValueError):
            decode_description(bomb, 'offer')
        value['sdp'] += 'm=audio 9 UDP/TLS/RTP/SAVPF 0\r\n'
        extra = PREFIX + base64.urlsafe_b64encode(zlib.compress(json.dumps(value).encode())).decode()
        with self.assertRaises(ValueError):
            decode_description(extra, 'offer')

    def test_answer_cannot_be_reapplied(self):
        _, answer = self.pair()
        with self.assertRaises(ValueError):
            self.host.accept_answer(answer)

    def test_wrong_kind_and_wrong_room_have_distinct_errors(self):
        offer = self.host.create_offer()
        with self.assertRaisesRegex(ValueError, 'no una respuesta'):
            decode_description(offer, 'answer')
        answer = self.guest.create_answer(offer)
        with self.assertRaisesRegex(ValueError, 'otra invitación'):
            decode_description(answer, 'answer', session='a' * 32)

    def test_host_lifetime_is_monotonic_and_expired_answer_rejected(self):
        answer = self.guest.create_answer(self.host.create_offer())
        self.host.invitation_deadline = time.monotonic() - 1
        with self.assertRaisesRegex(ValueError, '30 minutos'):
            self.host.accept_answer(answer)

    def test_diagnostics_show_signaling_without_secrets(self):
        self.host.create_offer()
        report = self.host.snapshot()
        self.assertTrue(report['clock_independent_expiry'])
        self.assertEqual(report['role'], 'host')
        self.assertFalse(report['remote_description_applied'])
        self.assertEqual(report['local_description_type'], 'offer')

    def test_close_without_signaling(self):
        self.host.close()
        self.assertTrue(self.host.done.is_set())
        with self.assertRaises(ValueError):
            self.host.create_offer()

    def test_game_bridge_real_sockets_and_cancel(self):
        self.pair()
        with socket.socket() as listener, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as hu, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as gu:
            listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(3)
            hu.bind(('127.0.0.1', 0)); gu.bind(('127.0.0.1', 0))
            hu.settimeout(3); gu.settimeout(3)
            self.host.attach_game(listener.getsockname()[1])
            hr, _ = listener.accept()
            guest_port = self.guest.attach_game()
            gr = socket.create_connection(('127.0.0.1', guest_port), timeout=3)
            try:
                gr.sendall(CONTROL.pack(MAGIC, 7, 1, gu.getsockname()[1], 0, 0))
                hello = CONTROL.unpack(hr.recv(24))
                hr.sendall(CONTROL.pack(MAGIC, 7, 2, hu.getsockname()[1], 0, 42))
                accept = CONTROL.unpack(gr.recv(24))
                for sock, port, other in ((gu, accept[3], hu), (hu, hello[3], gu)):
                    data = b'TM3O' + bytes(48) + b'ice-payload'
                    sock.sendto(data, ('127.0.0.1', port))
                    self.assertEqual(other.recv(2048), data)
                cancel = CONTROL.pack(MAGIC, 7, 5, 0, 0, 42)
                gr.sendall(cancel)
                self.assertEqual(hr.recv(24), cancel)
                self.assertTrue(self.host.connected.is_set())
                self.assertTrue(self.guest.connected.is_set())
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as intruder:
                    intruder.sendto(b'TM3O' + bytes(48), ('127.0.0.1', hello[3]))
                time.sleep(.03)
                self.assertEqual(self.host.sent, 1)
            finally:
                hr.close(); gr.close()


if __name__ == '__main__':
    unittest.main()
