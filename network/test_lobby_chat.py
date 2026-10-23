"""Room-chat privacy and delivery through actual loopback HTTP."""
import secrets
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from lobby_client import api
from lobby_server import Directory, Handler, CHAT_HISTORY


class ChatTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Directory(Path(self.temp.name) / "users.sqlite3")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.directory = self.directory
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.host, self.guest, self.observer, self.other_host = [
            api(self.url, dict(op="login", name=name, secret=secrets.token_hex(32)))["token"]
            for name in ("Nelson", "Sofia", "Alex", "Oscar")]
        self.rid = self.request(self.host, "create")["room"]["id"]
        self.request(self.guest, "join", room=self.rid)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.db.close()
        self.temp.cleanup()

    def request(self, token, op="poll", **kwargs):
        return api(self.url, dict(op=op, token=token, **kwargs))

    def test_both_players_receive_messages_in_order(self):
        self.request(self.host, "chat", text="Hola Sofia")
        self.request(self.guest, "chat", text="Hola Nelson")
        messages = self.request(self.host)["room"]["chat"]
        self.assertEqual(messages, self.request(self.guest)["room"]["chat"])
        self.assertEqual([m["text"] for m in messages[-2:]], ["Hola Sofia", "Hola Nelson"])
        self.assertLess(messages[-2]["id"], messages[-1]["id"])

    def test_observer_sees_rooms_but_not_chat(self):
        self.request(self.host, "chat", text="Privado de la sala")
        state = self.request(self.observer)
        self.assertEqual(state["rooms"][0]["chat"], [])
        self.assertIsNone(state["room"])

    def test_outsider_cannot_send_to_room(self):
        with self.assertRaises(ValueError):
            self.request(self.observer, "chat", room=self.rid, text="Intruso")

    def test_messages_cannot_spoof_sender(self):
        self.request(self.guest, "chat", text="Hola", name="Nelson")
        self.assertEqual(self.request(self.host)["room"]["chat"][-1]["name"], "Sofia")

    def test_two_rooms_have_independent_histories(self):
        other = self.request(self.other_host, "create")["room"]
        self.request(self.observer, "join", room=other["id"])
        self.request(self.host, "chat", text="Solo sala Nelson")
        self.request(self.other_host, "chat", text="Solo sala Oscar")
        self.assertNotIn("Solo sala Oscar", str(self.request(self.guest)["room"]["chat"]))
        self.assertNotIn("Solo sala Nelson", str(self.request(self.observer)["room"]["chat"]))

    def test_unicode_and_maximum_message_length(self):
        self.request(self.host, "chat", text="🎮" * 500)
        self.assertEqual(self.request(self.guest)["room"]["chat"][-1]["text"], "🎮" * 500)

    def test_invalid_message_inputs_are_rejected(self):
        for text in (None, True, 123, "", "   ", "a" * 501, "Al\x00ex"):
            with self.subTest(text=str(text)[:20]), self.assertRaises(ValueError):
                self.request(self.host, "chat", text=text)

    def test_history_is_bounded_and_ids_keep_increasing(self):
        for i in range(CHAT_HISTORY + 3):
            self.request(self.host, "chat", text=f"Mensaje {i}")
        messages = self.request(self.guest)["room"]["chat"]
        self.assertEqual(len(messages), CHAT_HISTORY)
        self.assertEqual(messages[-1]["text"], f"Mensaje {CHAT_HISTORY + 2}")
        self.assertEqual(len({m["id"] for m in messages}), CHAT_HISTORY)

    def test_guest_exit_is_announced_and_access_is_removed(self):
        self.request(self.guest, "leave")
        self.assertIn("Sofia salió", self.request(self.host)["room"]["chat"][-1]["text"])
        with self.assertRaises(ValueError):
            self.request(self.guest, "chat", text="Ya salí")

    def test_room_description_is_visible_to_observers(self):
        self.request(self.other_host, "create", description="Combate 6 CPU + 2 humanos")
        rooms = self.request(self.observer)["rooms"]
        self.assertIn("Combate 6 CPU + 2 humanos", [r["description"] for r in rooms])

    def test_invalid_descriptions_are_rejected(self):
        for value in (None, "", " ", "a" * 101, "Linea\nnueva", 123):
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError):
                self.request(self.other_host, "create", description=value)


if __name__ == "__main__":
    unittest.main()
