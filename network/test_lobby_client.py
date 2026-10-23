"""Client startup and layout regressions. No game launches or real profile writes."""
import queue
import socket
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import tkinter as tk
from lobby_client import Lobby, discover
import lobby_language as loc


class DiscoveryTest(unittest.TestCase):
    def test_windows_closed_udp_port_is_not_fatal(self):
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.recvfrom.side_effect = [OSError(10054, "Connection reset"), socket.timeout(), socket.timeout()]
        with patch("lobby_client.socket.socket", return_value=fake), \
             patch("lobby_client.time.monotonic", side_effect=[0, 0, .25, .5, 1.1]):
            self.assertIsNone(discover())
        self.assertEqual(fake.sendto.call_count, 2)

    def test_discovery_continues_after_windows_reset(self):
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.recvfrom.side_effect = [OSError(10054, "Connection reset"), (b"TM3_LOBBY_V1 27890", ("192.0.2.10", 27890))]
        with patch("lobby_client.socket.socket", return_value=fake), \
             patch("lobby_client.time.monotonic", side_effect=[0, 0, .5, 1.1]), \
             patch("lobby_client.api", return_value={"service": "TM3Lobby"}):
            self.assertEqual(discover(), "http://192.0.2.10:27890")

    def test_other_udp_errors_are_not_silenced(self):
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.recvfrom.side_effect = OSError(10013, "Access denied")
        with patch("lobby_client.socket.socket", return_value=fake), self.assertRaises(OSError):
            discover()


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        # In-memory widgets; forbid automatic connections and real profile I/O.
        with patch.object(Lobby, "connect"), patch.object(Path, "read_text", side_effect=FileNotFoundError), \
             patch.object(Path, "mkdir"):
            self.app = Lobby(self.root)
        # Existing regression assertions exercise the Spanish option.
        loc.language = "es"
        self.show_patch = patch.object(self.app, "show_room")
        self.show_patch.start()
        self.root.after_cancel(self.root.tk.call("after", "info")[-1])

    def tearDown(self):
        self.show_patch.stop()
        self.root.destroy()

    def room(self, owner=True, players=None):
        return dict(id="qa-room", host="Nelson", players=players or ["Nelson"], owner=owner,
                    capacity=2, joinable=True, phase="waiting", generation=0, error="", address="127.0.0.1")

    def render_room(self, room):
        self.app.token = "qa-session"
        self.app.render({"room": room, "rooms": [room] if room else []})

    def test_all_information_fits_minimum_window(self):
        self.root.geometry("780x620")
        self.app.error_detail.configure(text="Detalle del error: [WinError 10054] " + "Mensaje de diagnóstico largo. " * 5)
        self.root.update_idletasks()
        for widget in (self.app.identity, self.app.connection, self.app.table, self.app.status, self.app.error_detail, self.app.retry):
            self.assertGreater(widget.winfo_height(), 0)
            bottom = widget.winfo_rooty() + widget.winfo_height() - self.root.winfo_rooty()
            self.assertLessEqual(bottom, self.root.winfo_height(), widget.winfo_class())

    def test_local_button_available_without_directory(self):
        self.assertEqual(str(self.app.local_button["state"]), "normal")
        with patch.object(self.app, "launch_game", return_value=MagicMock()) as launch:
            self.app.play_local()
        launch.assert_called_once_with("lobby_local", [])
        self.assertIsNotNone(self.app.local_process)
        self.assertIsNone(self.app.process)

    def test_public_directory_setting_preserves_runtime_and_requires_https(self):
        self.app.config = {"runtime": {"executable": "custom/runtime.exe"}}
        with tempfile.TemporaryDirectory() as folder, patch("lobby_client.ROOT", Path(folder)):
            with patch("lobby_client.simpledialog.askstring", return_value="https://lobby.example/" ):
                self.app.configure_directory()
            import json
            saved = json.loads((Path(folder) / "TM3Lobby.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["directory_url"], "https://lobby.example")
            self.assertEqual(saved["runtime"], self.app.config["runtime"])
            with patch("lobby_client.simpledialog.askstring", return_value="http://insecure.example"), \
                 patch("lobby_client.messagebox.showerror") as error:
                self.app.configure_directory()
            error.assert_called_once()
            self.assertEqual(self.app.config["directory_url"], "https://lobby.example")
            with patch("lobby_client.simpledialog.askstring", return_value=""):
                self.app.configure_directory()
            self.assertEqual(self.app.config['directory_url'], '')
            self.assertEqual(self.app.config["runtime"], saved["runtime"])

    def test_relay_room_explains_connection_mode(self):
        room = self.room()
        room["connection_mode"] = "relay"
        self.render_room(room)
        self.assertIn("relay", self.app.room_note.cget("text"))

    def test_manual_p2p_window_removed(self):
        self.assertFalse(hasattr(self.app, 'p2p_button'))
        self.assertFalse(hasattr(self.app, 'open_p2p'))

    def test_automatic_connect_phase_visible_in_room(self):
        room = self.room(players=['Nelson', 'Sofia'])
        room.update(phase='connect', connection_mode='ice')
        self.render_room(room)
        self.assertIn('automáticamente', self.app.room_status.cget('text'))
        self.assertEqual(str(self.app.start_button['state']), 'disabled')

    def test_peer_ping_waiting_then_live_in_both_windows_and_localized(self):
        room = self.room(players=['Nelson', 'Sofia'])
        room.update(phase='playing', connection_mode='ice')
        self.render_room(room)
        self.assertIn('se medirá', self.app.room_latency.cget('text'))
        peer = self.app.ice_peer = MagicMock()
        peer.latency_snapshot.return_value = dict(connected=True, samples=3, stale=False,
            rtt_ms=42.5, average_ms=44.1, variation_ms=3.2)
        self.app.refresh_latency()
        text = self.app.room_latency.cget('text')
        self.assertIn('42.5 ms', text)
        self.assertIn('Promedio: 44.1 ms', text)
        self.assertIn('Variación: 3.2 ms', text)
        self.assertEqual(self.app.latency_label.cget('text'), text)
        loc.language = 'en'
        self.app.refresh_latency()
        self.assertIn('Average: 44.1 ms', self.app.room_latency.cget('text'))

    def test_stale_ping_does_not_present_old_number_as_current(self):
        room = self.room(players=['Nelson', 'Sofia'])
        room.update(phase='playing', connection_mode='ice')
        self.render_room(room)
        peer = self.app.ice_peer = MagicMock()
        peer.latency_snapshot.return_value = dict(connected=True, samples=1, stale=True,
            rtt_ms=987.0, average_ms=987.0, variation_ms=0)
        self.app.refresh_latency()
        self.assertIn('sin muestra reciente', self.app.room_latency.cget('text'))
        self.assertNotIn('987', self.app.room_latency.cget('text'))
        peer.latency_snapshot.return_value = dict(connected=False, samples=1)
        self.app.refresh_latency()
        self.assertIn('esperando conexión', self.app.room_latency.cget('text'))
        self.render_room(None)
        self.assertEqual(self.app.latency_label.winfo_manager(), '')

    def test_ping_is_not_fabricated_for_legacy_lan_or_relay(self):
        self.render_room(self.room())
        self.assertIn('no disponible', self.app.room_latency.cget('text'))

    def test_guest_launches_against_owned_loopback_bridge(self):
        room = self.room(owner=False, players=["Nelson", "Sofia"])
        room.update(phase="client", connection_mode="relay", transport={"mode": "relay", "protocol": 1})
        bridge = MagicMock(local_port=41001)
        bridge.done.is_set.return_value = False
        with patch("lobby_client.RelayBridge", return_value=bridge), \
             patch.object(self.app, "runtime", return_value=(Path("game.exe"), Path("core.dll"), Path("game.cue"))), \
             patch.object(self.app, "launch_game") as launch, \
             patch.object(self.app, "session_state", return_value={"state": "connected"}):
            self.app.advance(room)
        bridge.start.assert_called_once_with(self.app.room_cancel)
        launch.assert_called_once_with("lobby_client", ["--join", "127.0.0.1:41001"])
        self.app.close_relay()
        bridge.close.assert_called_once()

    def test_relay_room_missing_ticket_cannot_fall_back_to_direct(self):
        room = self.room(owner=False, players=["Nelson", "Sofia"])
        room.update(phase="client", connection_mode="relay")
        with patch.object(self.app, "runtime", return_value=(Path("game.exe"), Path("core.dll"), Path("game.cue"))), \
             patch.object(self.app, "launch_game") as launch:
            self.app.advance(room)
        launch.assert_not_called()
        self.assertEqual(self.app.actions.get_nowait()["op"], "failed")

    def test_english_translation_preserves_player_content(self):
        loc.language = "en"
        self.app.identity.configure(text="Bienvenido, Nelson")
        self.assertEqual(self.app.identity.cget("text"), "Welcome, Nelson")
        self.assertEqual(loc.tr("Custom player text"), "Custom player text")
        self.assertEqual(loc.tr("Jugar local"), "Play locally")

    def test_local_refuses_room_and_pending_requests(self):
        with patch.object(self.app, "launch_game") as launch, patch("lobby_client.messagebox.showerror"):
            self.app.actions.put({"op": "create"})
            self.app.play_local()
            self.app.actions.get_nowait()
            self.render_room(self.room())
            self.app.play_local()
        launch.assert_not_called()
        self.assertEqual(str(self.app.local_button["state"]), "disabled")

    def test_capture_variables_not_inherited(self):
        self.app.config = {"runtime": {"environment": {"TM3O_CPU_BUDGET_PERCENT": "175"}}}
        with patch.dict("os.environ", {"TM3O_PACING_FILE": "old.csv", "TM3O_CPU_BUDGET_PERCENT": "150"}):
            environment = self.app.game_environment("local")
        self.assertNotIn("TM3O_PACING_FILE", environment)
        self.assertEqual(environment["TM3O_CPU_BUDGET_PERCENT"], "175")

    def test_local_process_blocks_runtime_and_survives_room_cleanup(self):
        self.app.local_process = MagicMock()
        self.app.local_process.poll.return_value = None
        with patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", return_value=""):
            with self.assertRaisesRegex(ValueError, "sigue abierto"):
                self.app.runtime()
        self.app.stop_room_process()
        self.app.local_process.terminate.assert_not_called()

    def test_local_command_has_no_network_arguments(self):
        paths = (Path("C:/package/TM3Online.exe"), Path("C:/package/core.dll"), Path("C:/package/game.cue"))
        with patch.object(self.app, "runtime", return_value=paths), patch("lobby_client.subprocess.Popen") as spawn:
            self.app.play_local()
        command = spawn.call_args.args[0]
        self.assertNotIn("--host", command)
        self.assertNotIn("--join", command)
        self.assertEqual(command[-2:], ["--save-slot", "lobby_local"])

    def test_welcome_retains_username_when_disconnected(self):
        self.app.profile = {"name": "Nelson"}
        self.app.identity.configure(text="Bienvenido, Nelson")
        self.app.events.put(("disconnected", "[WinError 10054] Error de prueba"))
        self.app.drain()
        self.assertEqual(self.app.identity.cget("text"), "Bienvenido, Nelson")
        self.assertEqual(self.app.connection.cget("text"), "Sin conexión")
        self.assertIn("Reconectar", self.app.status.cget("text"))
        self.assertIn("10054", self.app.error_detail.cget("text"))

    def test_connected_welcome_and_empty_room_guidance(self):
        self.app.profile = {"name": "Nelson"}
        self.app.events.put(("connected", None))
        self.app.events.put(("state", {"rooms": [], "room": None}))
        self.app.drain()
        self.assertEqual(self.app.identity.cget("text"), "Bienvenido, Nelson")
        self.assertIn("Crear sala", self.app.status.cget("text"))

    def test_create_opens_separate_room_window(self):
        self.render_room(self.room())
        self.assertIsInstance(self.app.room_window, tk.Toplevel)
        self.assertIsNot(self.app.room_window, self.root)
        self.assertEqual(len(self.app.table.get_children()), 1)
        self.assertIn("Sala de Nelson", self.app.room_window.title())

    def test_join_opens_separate_guest_room(self):
        self.render_room(self.room(owner=False, players=["Nelson", "Sofia"]))
        self.assertIn("invitado", self.app.room_role.cget("text"))
        self.assertEqual(self.app.start_button.winfo_manager(), "")
        self.assertEqual(self.app.leave_button.cget("text"), "Salir de la sala")

    def test_host_controls_are_inside_room_not_lobby(self):
        self.render_room(self.room(players=["Nelson", "Sofia"]))
        self.assertEqual(str(self.app.start_button["state"]), "normal")
        self.assertTrue(str(self.app.start_button).startswith(str(self.app.room_window)))
        self.assertEqual(self.app.leave_button.cget("text"), "Cerrar sala")

    def test_host_alone_has_empty_slot_and_disabled_start(self):
        self.render_room(self.room())
        self.assertEqual(str(self.app.start_button["state"]), "disabled")
        self.assertEqual(self.app.room_players.item("1")["values"][2], "Disponible")

    def test_poll_updates_existing_window_without_opening_duplicates(self):
        self.render_room(self.room())
        first = self.app.room_window
        self.render_room(self.room(players=["Nelson", "Sofia"]))
        self.assertIs(self.app.room_window, first)
        self.assertEqual(self.app.room_players.item("1")["values"][1], "Sofia")
        self.assertEqual(str(self.app.start_button["state"]), "normal")

    def test_room_close_requests_leave_and_preserves_lobby(self):
        self.render_room(self.room())
        self.app.leave_room()
        self.assertEqual(self.app.actions.get_nowait()["op"], "leave")
        self.assertTrue(self.root.winfo_exists())
        self.assertFalse(self.app.stop.is_set())
        self.assertEqual(str(self.app.start_button["state"]), "disabled")

    def test_leave_confirmation_closes_room_only(self):
        self.render_room(self.room())
        self.render_room(None)
        self.assertIsNone(self.app.room_window)
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(str(self.app.create_button["state"]), "normal")

    def test_disconnect_closes_room_and_disables_actions(self):
        self.render_room(self.room())
        self.app.events.put(("disconnected", "Prueba"))
        self.app.drain()
        self.assertIsNone(self.app.room_window)
        self.assertEqual(str(self.app.create_button["state"]), "disabled")
        self.assertFalse(hasattr(self.app, "show_room_button"))

    def test_room_footer_fits_minimum_size(self):
        room = self.room(players=["Nelson", "Sofia"])
        room["error"] = "Detalle de error largo. " * 10
        self.render_room(room)
        window = self.app.room_window
        window.attributes("-alpha", 0)
        window.deiconify()
        window.geometry("700x620")
        self.root.update_idletasks()
        for widget in (self.app.room_status, self.app.start_button, self.app.leave_button):
            bottom = widget.winfo_rooty() + widget.winfo_height() - window.winfo_rooty()
            self.assertLessEqual(bottom, window.winfo_height(), widget.winfo_class())

    def test_room_opens_automatically_without_view_button(self):
        self.render_room(self.room())
        self.app.show_room.assert_called_once()
        self.assertFalse(hasattr(self.app, "show_room_button"))

    def test_create_prompts_for_room_description(self):
        self.app.token = "qa-session"
        with patch("lobby_client.simpledialog.askstring", return_value="Partida de 6 CPU"):
            self.app.create_room()
        self.assertEqual(self.app.actions.get_nowait(), {"op": "create", "description": "Partida de 6 CPU"})

    def test_cancel_description_does_not_create_room(self):
        self.app.token = "qa-session"
        with patch("lobby_client.simpledialog.askstring", return_value=None):
            self.app.create_room()
        self.assertTrue(self.app.actions.empty())

    def test_chat_entry_sends_text_with_enter_handler(self):
        self.render_room(self.room())
        self.app.chat_input.insert(0, " Hola Sofia ")
        self.assertEqual(self.app.send_chat(), "break")
        self.assertEqual(self.app.actions.get_nowait(), {"op": "chat", "text": "Hola Sofia"})
        self.assertEqual(self.app.chat_input.get(), "")

    def test_chat_rejects_oversized_text_before_sending(self):
        self.render_room(self.room())
        self.app.chat_input.insert(0, "a" * 501)
        self.app.send_chat()
        self.assertTrue(self.app.actions.empty())
        self.assertIn("500", self.app.room_status.cget("text"))

    def test_chat_poll_does_not_duplicate_messages(self):
        room = self.room()
        room["chat"] = [dict(id=1, name="Sofia", text="Hola <Nelson>", kind="text", time=0)]
        self.render_room(room)
        self.render_room(room)
        text = self.app.chat_log.get("1.0", "end")
        self.assertEqual(text.count("Hola <Nelson>"), 1)
        self.assertEqual(str(self.app.chat_log["state"]), "disabled")

    def test_closing_room_cancels_pending_game_start(self):
        self.render_room(self.room())
        self.app.leave_room()
        with patch.object(self.app, "runtime") as runtime:
            self.app.advance(self.room())
        runtime.assert_not_called()
        self.assertTrue(self.app.room_cancel.is_set())

    def test_stop_only_terminates_the_tracked_room_process(self):
        process = self.app.process = MagicMock()
        process.poll.return_value = None
        self.app.stop_room_process()
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=3)
        self.assertIsNone(self.app.process)

    def test_leave_command_returns_room_to_menu_before_notifying_server(self):
        self.app.profile = dict(name="Nelson", secret="0" * 64)
        self.app.profile_path = MagicMock()
        process = self.app.process = MagicMock()
        process.poll.return_value = None
        self.app.actions.put({"op": "poll"})
        self.app.actions.put({"op": "leave"})
        room = self.room(players=["Nelson", "Sofia"])
        def fake_api(url, data):
            if data["op"] == "login":
                return {"token": "qa-token"}
            if data["op"] == "leave":
                self.app.return_room_process.assert_called()
                self.app.stop.set()
                return {"room": None, "rooms": []}
            if data["op"] == "logout":
                return {}
            return {"room": room, "rooms": [room]}
        with patch.object(self.app, "find_directory", return_value="http://127.0.0.1"), \
             patch("lobby_client.local_ip", return_value="127.0.0.1"), \
             patch("lobby_client.api", side_effect=fake_api), patch.object(self.app, "advance"), \
             patch.object(self.app, "return_room_process"):
            self.app.run()
        process.terminate.assert_not_called()

    def test_close_stops_both_owned_games_and_embedded_server(self):
        linked, local, directory = MagicMock(), MagicMock(), MagicMock()
        self.app.process, self.app.local_process, self.app.owned_directory = linked, local, directory
        with patch.object(self.app, "close_process") as close, patch.object(self.root, "destroy"):
            self.app.close()
        self.assertEqual(close.call_args_list, [unittest.mock.call(linked), unittest.mock.call(local)])
        directory.close.assert_called_once()
        self.assertTrue(self.app.stop.is_set())

    def test_return_event_only_signals_owned_session(self):
        self.app.process = MagicMock()
        self.app.process.poll.return_value = None
        self.app.return_event = 123
        with patch("lobby_client.ctypes.windll.kernel32.SetEvent") as signal:
            self.app.return_room_process()
        self.assertEqual(signal.call_args.args[0].value, 123)


if __name__ == "__main__":
    unittest.main()
