"""69 isolated QA cases over real loopback HTTP. No games, public services or real profiles."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lobby_client import api
from lobby_server import Directory, Handler


class LobbyQA(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="tm3_qa_")
        self.database = Path(self.folder.name) / "users.sqlite3"
        self.directory = Directory(self.database)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.directory = self.directory
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.credentials = {}
        self.host = self.login("Nelson")
        self.guest = self.login("Sofia")
        self.observer = self.login("Alex")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.directory.db.close()
        self.folder.cleanup()

    def login(self, name, secret=None, **kwargs):
        secret = secret or secrets.token_hex(32)
        result = api(self.url, dict(op="login", name=name, secret=secret, lan="192.168.1.10", **kwargs))
        self.credentials[str(name)] = secret
        return result["token"]

    def request(self, token, op="poll", **kwargs):
        return api(self.url, dict(token=token, op=op, **kwargs))

    def reject(self, token, op, **kwargs):
        with self.assertRaises(ValueError):
            self.request(token, op, **kwargs)

    def pair(self):
        room = self.request(self.host, "create")["room"]
        self.request(self.guest, "join", room=room["id"])
        return room["id"]

    def start(self, phase="prepare"):
        self.pair()
        generation = self.request(self.host, "start")["room"]["generation"]
        if phase != "prepare":
            self.request(self.host, "ready", generation=generation)
            self.request(self.guest, "ready", generation=generation)
        if phase in ("client", "playing"):
            self.request(self.host, "host_started", generation=generation)
        if phase == "playing":
            self.request(self.guest, "client_started", generation=generation)
        return generation

    def phase(self):
        return self.request(self.host)["room"]["phase"]

    def age_session(self, token):
        with self.directory.lock:
            self.directory.sessions[token]["seen"] -= 21

    def age_start(self):
        with self.directory.lock:
            self.directory.room_for(self.host)["since"] -= 26

    def raw_error(self, body):
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url, data=body, headers={"Content-Type": "application/json"}), timeout=3)
        with error.exception as response:
            self.assertEqual(response.code, 400)
            self.assertIn("error", json.load(response))
        self.assertEqual(api(self.url)["service"], "TM3Lobby")

    def test_01_login_returns_opaque_token(self):
        self.assertEqual(len(self.host), 64)
        self.assertNotEqual(self.host, self.guest)
        self.assertNotIn("Nelson", self.host)

    def test_02_unicode_username(self):
        token = self.login("Ángel")
        self.assertEqual(self.request(token, "create")["room"]["host"], "Ángel")

    def test_03_username_trimmed(self):
        token = self.login("  Oscar  ")
        self.assertEqual(self.request(token, "create")["room"]["host"], "Oscar")

    def test_04_minimum_username_length(self):
        token = self.login("AB")
        self.assertIsNone(self.request(token)["room"])

    def test_05_maximum_username_length(self):
        token = self.login("A" * 24)
        self.assertEqual(self.request(token, "create")["room"]["host"], "A" * 24)

    def test_06_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            self.login("")

    def test_07_short_name_rejected(self):
        with self.assertRaises(ValueError):
            self.login("A")

    def test_08_long_name_rejected(self):
        with self.assertRaises(ValueError):
            self.login("A" * 25)

    def test_09_punctuation_rejected(self):
        with self.assertRaises(ValueError):
            self.login("<script>")

    def test_10_control_character_rejected(self):
        with self.assertRaises(ValueError):
            self.login("Al\nex")

    def test_11_case_insensitive_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            self.login("NELSON")

    def test_12_normalized_unicode_duplicate_rejected(self):
        self.login("Ángel")
        with self.assertRaises(ValueError):
            self.login("A\u0301ngel")

    def test_13_concurrent_same_profile_rejected(self):
        with self.assertRaises(ValueError):
            self.login("Nelson", self.credentials["Nelson"])

    def test_14_reserved_name_rejects_wrong_secret_after_logout(self):
        self.request(self.host, "logout")
        with self.assertRaises(ValueError):
            self.login("Nelson")

    def test_15_profile_reconnects_after_logout(self):
        secret = self.credentials["Nelson"]
        self.request(self.host, "logout")
        token = self.login("Nelson", secret)
        self.assertNotEqual(token, self.host)
        self.assertEqual(self.request(token)["rooms"], [])

    def test_16_reservation_survives_directory_restart(self):
        other = Directory(self.database)
        try:
            with self.assertRaises(ValueError):
                other.request(dict(op="login", name="Nelson", secret=secrets.token_hex(32)), "127.0.0.1")
            row = other.db.execute("SELECT secret FROM users WHERE name='nelson'").fetchone()
            self.assertEqual(row[0], hashlib.sha256(self.credentials["Nelson"].encode()).hexdigest())
            self.assertEqual(other.rooms, {})
        finally:
            other.db.close()

    def test_17_short_profile_secret_rejected(self):
        with self.assertRaises(ValueError):
            self.login("Oscar", "abc")

    def test_18_missing_token_rejected(self):
        with self.assertRaises(ValueError):
            api(self.url, dict(op="poll"))

    def test_19_forged_token_rejected(self):
        self.reject("f" * 64, "poll")

    def test_20_logout_invalidates_token(self):
        self.request(self.host, "logout")
        self.reject(self.host, "poll")

    def test_21_idle_session_expires(self):
        self.age_session(self.host)
        self.reject(self.host, "poll")

    def test_22_poll_refreshes_presence(self):
        with self.directory.lock:
            self.directory.sessions[self.host]["seen"] -= 10
            before = self.directory.sessions[self.host]["seen"]
        self.request(self.host)
        with self.directory.lock:
            self.assertGreater(self.directory.sessions[self.host]["seen"], before + 5)

    def test_23_created_room_contains_host_only(self):
        room = self.request(self.host, "create")["room"]
        self.assertEqual(room["players"], ["Nelson"])
        self.assertTrue(room["owner"])
        self.assertEqual(room["capacity"], 2)

    def test_24_observers_see_room_without_joining(self):
        rid = self.request(self.host, "create")["room"]["id"]
        for token in (self.guest, self.observer):
            state = self.request(token)
            self.assertIsNone(state["room"])
            self.assertEqual([r["id"] for r in state["rooms"]], [rid])

    def test_25_four_accounts_see_both_hosts(self):
        fourth = self.login("Oscar")
        self.request(self.host, "create")
        self.request(fourth, "create")
        for token in (self.host, self.guest, self.observer, fourth):
            self.assertEqual({r["host"] for r in self.request(token)["rooms"]}, {"Nelson", "Oscar"})

    def test_26_one_room_per_host(self):
        self.request(self.host, "create")
        self.reject(self.host, "create")
        self.assertEqual(len(self.request(self.host)["rooms"]), 1)

    def test_27_owner_cannot_join_own_room_twice(self):
        room = self.request(self.host, "create")["room"]
        self.reject(self.host, "join", room=room["id"])
        self.assertEqual(self.request(self.host)["room"]["players"], ["Nelson"])

    def test_28_guest_joins_and_room_becomes_full(self):
        self.pair()
        room = self.request(self.guest)["room"]
        self.assertEqual(room["players"], ["Nelson", "Sofia"])
        self.assertFalse(room["joinable"])

    def test_29_third_player_cannot_join(self):
        rid = self.pair()
        self.reject(self.observer, "join", room=rid)
        self.assertIsNone(self.request(self.observer)["room"])

    def test_30_missing_room_id_rejected(self):
        self.reject(self.guest, "join")

    def test_31_unknown_room_id_rejected(self):
        self.reject(self.guest, "join", room="nonexistent")

    def test_32_member_cannot_join_another_room(self):
        self.pair()
        rid = self.request(self.observer, "create")["room"]["id"]
        self.reject(self.guest, "join", room=rid)
        self.assertEqual(self.request(self.guest)["room"]["host"], "Nelson")

    def test_33_guest_leaving_reopens_slot(self):
        self.pair()
        self.request(self.guest, "leave")
        self.assertTrue(self.request(self.host)["room"]["joinable"])

    def test_34_owner_leaving_removes_announcement(self):
        self.pair()
        self.request(self.host, "leave")
        self.assertEqual(self.request(self.observer)["rooms"], [])
        self.assertIsNone(self.request(self.guest)["room"])

    def test_35_guest_logout_reopens_slot(self):
        self.pair()
        self.request(self.guest, "logout")
        self.assertEqual(self.request(self.host)["room"]["players"], ["Nelson"])

    def test_36_host_logout_removes_room(self):
        self.pair()
        self.request(self.host, "logout")
        self.assertEqual(self.request(self.guest)["rooms"], [])

    def test_37_abrupt_guest_disconnect_expires(self):
        self.pair()
        self.age_session(self.guest)
        self.assertTrue(self.request(self.host)["room"]["joinable"])

    def test_38_abrupt_host_disconnect_removes_room(self):
        self.pair()
        self.age_session(self.host)
        self.assertEqual(self.request(self.guest)["rooms"], [])

    def test_39_three_simultaneous_joins_accept_one(self):
        rid = self.request(self.host, "create")["room"]["id"]
        fourth = self.login("Oscar")
        barrier = threading.Barrier(3)
        def join(token):
            barrier.wait(timeout=5)
            try:
                self.request(token, "join", room=rid)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(sum(pool.map(join, (self.guest, self.observer, fourth))), 1)
        self.assertEqual(len(self.request(self.host)["room"]["players"]), 2)

    def test_40_concurrent_creates_cannot_duplicate_host_room(self):
        barrier = threading.Barrier(2)
        def create(_):
            barrier.wait(timeout=5)
            try:
                self.request(self.host, "create")
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(create, range(2))), 1)
        self.assertEqual(len(self.request(self.observer)["rooms"]), 1)

    def test_41_observer_cannot_read_game_endpoint_or_tokens(self):
        self.pair()
        state = self.request(self.observer)
        self.assertIsNone(state["rooms"][0]["address"])
        body = json.dumps(state)
        for sensitive in (self.host, self.guest, self.credentials["Nelson"], self.credentials["Sofia"]):
            self.assertNotIn(sensitive, body)

    def test_42_wan_address_uses_connection_source_not_profile(self):
        self.pair()
        # Inject two WAN source addresses. This is not a real WAN/NAT test.
        with self.directory.lock:
            self.directory.sessions[self.host]["ip"] = "198.51.100.10"
            self.directory.sessions[self.guest]["ip"] = "203.0.113.20"
        self.assertEqual(self.request(self.guest)["room"]["address"], "198.51.100.10")

    def test_43_observer_never_becomes_owner_by_polling(self):
        self.request(self.host, "create")
        state = self.request(self.observer)
        self.assertFalse(state["rooms"][0]["owner"])
        self.assertIsNone(state["room"])

    def test_44_start_requires_second_player(self):
        self.request(self.host, "create")
        self.reject(self.host, "start")

    def test_45_guest_cannot_start(self):
        self.pair()
        self.reject(self.guest, "start")
        self.assertEqual(self.phase(), "waiting")

    def test_46_observer_cannot_start(self):
        self.pair()
        self.reject(self.observer, "start")

    def test_47_host_start_prepares_both_clients(self):
        self.start()
        self.assertEqual(self.phase(), "prepare")
        self.assertEqual(self.request(self.guest)["room"]["phase"], "prepare")

    def test_48_double_start_rejected(self):
        self.start()
        self.reject(self.host, "start")

    def test_49_one_ready_client_does_not_start(self):
        generation = self.start()
        self.request(self.host, "ready", generation=generation)
        self.assertEqual(self.phase(), "prepare")

    def test_50_duplicate_ready_does_not_count_twice(self):
        generation = self.start()
        self.request(self.host, "ready", generation=generation)
        self.request(self.host, "ready", generation=generation)
        self.assertEqual(self.phase(), "prepare")

    def test_51_two_ready_clients_enable_host_launch(self):
        self.start("host")
        self.assertEqual(self.phase(), "host")

    def test_52_guest_cannot_confirm_host_launch(self):
        generation = self.start("host")
        self.request(self.guest, "host_started", generation=generation)
        self.assertEqual(self.phase(), "host")

    def test_53_premature_client_confirmation_ignored(self):
        generation = self.start("host")
        self.request(self.guest, "client_started", generation=generation)
        self.assertEqual(self.phase(), "host")

    def test_54_host_confirmation_enables_client_launch(self):
        self.start("client")
        self.assertEqual(self.phase(), "client")

    def test_55_host_cannot_confirm_guest_launch(self):
        generation = self.start("client")
        self.request(self.host, "client_started", generation=generation)
        self.assertEqual(self.phase(), "client")

    def test_56_guest_confirmation_marks_launch_complete(self):
        self.start("playing")
        self.assertEqual(self.phase(), "playing")

    def test_57_stale_start_confirmation_rejected(self):
        generation = self.start()
        self.reject(self.host, "ready", generation=generation - 1)

    def test_58_future_start_confirmation_rejected(self):
        generation = self.start()
        self.reject(self.host, "ready", generation=generation + 1)

    def test_59_preflight_failure_returns_room_to_waiting(self):
        generation = self.start()
        self.request(self.guest, "failed", generation=generation, error="Falta el core")
        room = self.request(self.host)["room"]
        self.assertEqual(room["phase"], "waiting")
        self.assertEqual(room["error"], "Falta el core")

    def test_60_retry_uses_new_generation(self):
        generation = self.start()
        self.request(self.guest, "failed", generation=generation)
        room = self.request(self.host, "start")["room"]
        self.assertGreater(room["generation"], generation)
        self.reject(self.guest, "ready", generation=generation)

    def test_61_prepare_timeout_recovers(self):
        self.start()
        self.age_start()
        self.assertEqual(self.phase(), "waiting")

    def test_62_host_launch_timeout_recovers(self):
        self.start("host")
        self.age_start()
        self.assertEqual(self.phase(), "waiting")

    def test_63_client_launch_timeout_recovers(self):
        self.start("client")
        self.age_start()
        self.assertEqual(self.phase(), "waiting")

    def test_64_late_failure_cannot_reopen_started_room(self):
        generation = self.start("playing")
        self.reject(self.guest, "failed", generation=generation, error="Mensaje tardio")
        self.assertEqual(self.phase(), "playing")

    def test_65_guest_leaving_during_start_cancels_launch(self):
        generation = self.start()
        self.request(self.guest, "leave")
        self.request(self.host, "ready", generation=generation)
        self.assertEqual(self.phase(), "waiting")
        self.assertEqual(self.request(self.host)["room"]["players"], ["Nelson"])

    def test_66_malformed_json_rejected_without_server_crash(self):
        self.raw_error(b'{"op":')

    def test_67_json_array_rejected_without_server_crash(self):
        self.raw_error(b'[]')

    def test_68_oversized_request_rejected_without_server_crash(self):
        self.raw_error(b' ' * 4097)

    def test_69_nontext_username_rejected(self):
        for value in (None, True, 1234, ["Ab"], {"name": "Ab"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.login(value)


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def startTest(self, test):
        self.started = time.perf_counter()
        self.outcome = "passed"
        super().startTest(test)

    def addFailure(self, test, err):
        self.outcome = "failed"
        super().addFailure(test, err)

    def addError(self, test, err):
        self.outcome = "error"
        super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.outcome = "failed" if issubclass(err[0], test.failureException) else "error"
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        self.records.append(dict(case=test.id().rsplit(".", 1)[-1], outcome=self.outcome,
                                 seconds=round(time.perf_counter() - self.started, 4)))
        super().stopTest(test)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LobbyQA)
    assert suite.countTestCases() == 69
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    sources = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
               for name in ("lobby_server.py", "lobby_client.py", "qa_lobby_69.py")}
    report = dict(time=datetime.now().astimezone().isoformat(), tests=result.testsRun,
                  passed=sum(r["outcome"] == "passed" for r in result.records),
                  failed=sum(r["outcome"] != "passed" for r in result.records),
                  successful=result.wasSuccessful(), sources_sha256=sources,
                  scope="69 control-plane cases over loopback HTTP; lifecycle timers injected. No game, WAN, CGNAT, NAT traversal or latency validation.",
                  real_profiles_modified=False, game_processes_launched=0, cases=result.records,
                  failures=[dict(case=str(case), detail=detail) for case, detail in result.failures + result.errors])
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# QA de lobby: 69 casos", "", f"Fecha: {report['time']}", "",
             f"Resultado: {report['passed']}/{report['tests']} aprobados; {report['failed']} casos fallidos.", "",
             report["scope"], "", "No se abrieron juegos ni se modificaron perfiles reales.", "",
             "| Caso | Resultado | Segundos |", "|---|---|---|"]
    lines.extend(f"| {r['case']} | {r['outcome']} | {r['seconds']} |" for r in result.records)
    for failure in report["failures"]:
        lines += ["", f"## {failure['case']}", "", "```text", failure["detail"], "```"]
    lines += ["", "## Versiones verificadas (SHA256)", ""]
    lines.extend(f"- {name}: `{digest}`" for name, digest in sources.items())
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
