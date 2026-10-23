"""Control-plane checks only. Does not launch the game or create real accounts."""
import secrets
import socket
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from http.server import ThreadingHTTPServer

from lobby_server import Directory, Handler, LocalDirectory
from lobby_client import api, listening


class LobbyTest(unittest.TestCase):
    def test_embedded_directory_releases_thread_and_socket(self):
        with tempfile.TemporaryDirectory() as folder:
            embedded = LocalDirectory(Path(folder) / "local.db", port=0)
            port = embedded.server.server_port
            self.assertEqual(api(f"http://127.0.0.1:{port}")["service"], "TM3Lobby")
            embedded.close()
            self.assertTrue(all(not thread.is_alive() for thread in embedded.threads))
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))

    def test_guest_can_cancel_and_both_players_stay_in_waiting_room(self):
        room = self.pair()
        generation = self.request(self.host, "start")["room"]["generation"]
        result = self.request(self.guest, "cancel", generation=generation)
        self.assertEqual(result["room"]["phase"], "waiting")
        self.assertEqual(len(result["room"]["players"]), 2)
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Directory(Path(self.temp.name) / "users.db")
        self.host_secret = secrets.token_hex(32)
        self.host = self.login("Nelson", self.host_secret, "127.0.0.1", "192.168.1.10")
        self.guest = self.login("Invitado", secrets.token_hex(32), "192.168.1.20", "192.168.1.20")

    def tearDown(self):
        self.directory.db.close()
        self.temp.cleanup()

    def login(self, name, secret, ip, lan):
        return self.directory.request(dict(op="login", name=name, secret=secret, lan=lan), ip)["token"]

    def request(self, token, op, **kwargs):
        return self.directory.request(dict(token=token, op=op, **kwargs), "127.0.0.1")

    def pair(self):
        room = self.request(self.host, "create")["room"]
        return self.request(self.guest, "join", room=room["id"])["room"]

    def test_reserved_names_and_concurrent_login(self):
        with self.assertRaisesRegex(ValueError, "ya existe"):
            self.login("NELSON", secrets.token_hex(32), "127.0.0.1", "127.0.0.1")
        with self.assertRaisesRegex(ValueError, "ya esta conectado"):
            self.login("Nelson", self.host_secret, "127.0.0.1", "127.0.0.1")
        self.request(self.host, "logout")
        self.host = self.login("Nelson", self.host_secret, "127.0.0.1", "192.168.1.10")

    def test_host_only_start_and_ordered_launch(self):
        room = self.pair()
        self.assertEqual(room["address"], "192.168.1.10")
        with self.assertRaises(ValueError):
            self.request(self.guest, "start")
        state = self.request(self.host, "start")["room"]
        generation = state["generation"]
        self.assertEqual(state["phase"], "prepare")
        self.assertEqual(self.request(self.host, "ready", generation=generation)["room"]["phase"], "prepare")
        self.assertEqual(self.request(self.guest, "ready", generation=generation)["room"]["phase"], "host")
        self.assertEqual(self.request(self.guest, "host_started", generation=generation)["room"]["phase"], "host")
        self.assertEqual(self.request(self.host, "host_started", generation=generation)["room"]["phase"], "client")
        self.assertEqual(self.request(self.guest, "client_started", generation=generation)["room"]["phase"], "playing")

    def test_full_room_leave_and_expiry(self):
        self.pair()
        third = self.login("Tercero", secrets.token_hex(32), "192.168.1.30", "192.168.1.30")
        rid = self.request(self.host, "poll")["room"]["id"]
        with self.assertRaises(ValueError):
            self.request(third, "join", room=rid)
        self.request(self.guest, "leave")
        self.assertEqual(len(self.request(self.host, "poll")["room"]["players"]), 1)
        self.directory.sessions[self.host]["seen"] -= 21
        self.assertEqual(self.request(self.guest, "poll")["rooms"], [])

    def test_all_users_see_all_rooms_and_each_room_has_two_slots(self):
        room_a = self.pair()
        second_host = self.login("Otro anfitrion", secrets.token_hex(32), "192.168.1.30", "192.168.1.30")
        second_guest = self.login("Otro invitado", secrets.token_hex(32), "192.168.1.40", "192.168.1.40")
        spectator = self.login("Observador", secrets.token_hex(32), "192.168.1.50", "192.168.1.50")
        room_b = self.request(second_host, "create")["room"]
        self.request(second_guest, "join", room=room_b["id"])
        for token in (self.host, self.guest, second_host, second_guest, spectator):
            rooms = self.request(token, "poll")["rooms"]
            self.assertEqual({r["id"] for r in rooms}, {room_a["id"], room_b["id"]})
            self.assertTrue(all(len(r["players"]) == 2 for r in rooms))
        for rid in (room_a["id"], room_b["id"]):
            with self.assertRaises(ValueError):
                self.request(spectator, "join", room=rid)
        self.request(self.host, "logout")
        self.assertEqual([r["id"] for r in self.request(spectator, "poll")["rooms"]], [room_b["id"]])

    def test_wan_address_is_detected_by_directory(self):
        self.directory.sessions[self.host].update(ip="198.51.100.10", lan="192.168.1.10")
        self.directory.sessions[self.guest].update(ip="203.0.113.20", lan="192.168.1.20")
        self.assertEqual(self.pair()["address"], "198.51.100.10")

    def test_simultaneous_joins_cannot_exceed_two_players(self):
        room = self.request(self.host, "create")["room"]
        third = self.login("Tercero", secrets.token_hex(32), "192.168.1.30", "192.168.1.30")
        fourth = self.login("Cuarto", secrets.token_hex(32), "192.168.1.40", "192.168.1.40")
        barrier = threading.Barrier(3)
        def join(token):
            barrier.wait(timeout=5)
            try:
                self.request(token, "join", room=room["id"])
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=3) as pool:
            accepted = list(pool.map(join, (self.guest, third, fourth)))
        self.assertEqual(sum(accepted), 1)
        self.assertEqual(len(self.request(self.host, "poll")["room"]["players"]), 2)

    def test_failed_start_can_retry_and_stale_ack_rejected(self):
        self.pair()
        generation = self.request(self.host, "start")["room"]["generation"]
        self.request(self.guest, "failed", generation=generation, error="Falta el core")
        state = self.request(self.host, "start")["room"]
        self.assertGreater(state["generation"], generation)
        with self.assertRaises(ValueError):
            self.request(self.host, "ready", generation=generation)

    def test_http_and_owning_pid_detection(self):
        import os
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.directory = self.directory
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            self.assertEqual(api(url)["service"], "TM3Lobby")
            self.assertTrue(listening(os.getpid(), server.server_port))
            self.assertFalse(listening(99999999, server.server_port))
            self.assertEqual(len(api(url, dict(op="poll", token=self.host))["rooms"]), 0)
            with self.assertRaises(ValueError):
                api(url, dict(op="poll", token="invalido"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
