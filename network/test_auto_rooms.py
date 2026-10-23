"""Automatic room signaling authorization, generations and TLS boundary."""
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from lobby_server import Directory
from worker_directory import WorkerDirectory


class AutomaticDirectoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Directory(Path(self.temp.name) / 'users.db', automatic_ice=True)
        self.tokens = [self.directory.request(dict(op='login', name=name, secret=secrets.token_hex(32), automatic_ice=1), ip)['token']
            for name, ip in (('Host', '198.51.100.10'), ('Guest', '203.0.113.20'), ('Observer', '192.0.2.30'))]
        self.host, self.guest, self.observer = self.tokens
        self.rid = self.request(self.host, 'create')['room']['id']
        self.request(self.guest, 'join', room=self.rid)
        self.generation = self.request(self.host, 'start')['room']['generation']

    def tearDown(self):
        self.directory.db.close()
        self.temp.cleanup()

    def request(self, token, op='poll', **kwargs):
        return self.directory.request(dict(token=token, op=op, **kwargs), '127.0.0.1')

    def signal(self, token, op, code='TM3ICE1.test'):
        return self.request(token, op, generation=self.generation, code=code)

    def test_offer_answer_private_and_not_replaced(self):
        self.signal(self.host, 'ice_offer')
        self.assertEqual(self.request(self.guest)['room']['transport']['offer'], 'TM3ICE1.test')
        self.assertIsNone(self.request(self.observer)['rooms'][0]['transport'])
        with self.assertRaises(ValueError):
            self.signal(self.host, 'ice_offer', 'TM3ICE1.changed')
        self.signal(self.guest, 'ice_answer', 'TM3ICE1.answer')
        self.assertEqual(self.request(self.host)['room']['transport']['answer'], 'TM3ICE1.answer')

    def test_outsiders_wrong_role_and_stale_generation_rejected(self):
        for token, op in ((self.guest, 'ice_offer'), (self.host, 'ice_answer'), (self.observer, 'ice_offer')):
            with self.assertRaises(ValueError):
                self.signal(token, op)
        with self.assertRaises(ValueError):
            self.request(self.host, 'ice_offer', generation=self.generation - 1, code='TM3ICE1.old')

    def test_ready_transition_and_fresh_retry(self):
        self.signal(self.host, 'ice_offer')
        self.signal(self.guest, 'ice_answer')
        self.signal(self.host, 'ice_ready')
        self.assertEqual(self.signal(self.guest, 'ice_ready')['room']['phase'], 'prepare')
        self.request(self.host, 'failed', generation=self.generation, error='retry')
        state = self.request(self.host, 'start')['room']
        self.assertEqual(state['generation'], self.generation + 1)
        self.assertNotIn('answer', state['transport'])

    def test_negotiation_times_out_and_invalid_payload_is_bounded(self):
        with self.assertRaises(ValueError):
            self.signal(self.host, 'ice_offer', 'x' * 32001)
        self.directory.rooms[self.rid]['since'] -= 91
        self.assertEqual(self.request(self.host)['room']['phase'], 'waiting')


class WorkerClientTest(unittest.TestCase):
    def test_tls_required_before_connect_and_no_url_credentials(self):
        for url in ('http://example.com', 'https://user:password@example.com', 'https://example.com/?secret=bad'):
            with patch('websockets.sync.client.connect') as connect:
                with self.assertRaises(ValueError):
                    WorkerDirectory(url)
                connect.assert_not_called()

    def test_rpc_uses_same_request_identity_and_reports_server_errors(self):
        socket = MagicMock()
        with patch('websockets.sync.client.connect', return_value=socket) as connect:
            client = WorkerDirectory('https://rooms.example')
        self.assertEqual(connect.call_args.args[0], 'wss://rooms.example/ws')
        self.assertEqual(connect.call_args.kwargs['user_agent_header'], 'TM3Lobby/3')
        socket.recv.return_value = json.dumps(dict(id=1, result={'token': 'test'}))
        self.assertEqual(client.request(dict(op='login')), {'token': 'test'})
        self.assertEqual(json.loads(socket.send.call_args.args[0])['id'], 1)
        socket.recv.return_value = json.dumps(dict(id=2, error='Room full'))
        with self.assertRaisesRegex(ValueError, 'Room full'):
            client.request(dict(op='join'))
        socket.recv.return_value = json.dumps(dict(id=999, result={}))
        with self.assertRaisesRegex(ValueError, 'inesperada'):
            client.request(dict(op='poll'))
        client.close()
        socket.close.assert_called_once()

    def test_health_request_identifies_the_real_application(self):
        from lobby_client import api
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"service":"TM3Lobby"}'
        with patch('lobby_client.urlopen', return_value=response) as request:
            self.assertEqual(api('https://rooms.example'), {'service': 'TM3Lobby'})
        self.assertEqual(request.call_args.args[0].get_header('User-agent'), 'TM3Lobby/3')


if __name__ == '__main__':
    unittest.main()
