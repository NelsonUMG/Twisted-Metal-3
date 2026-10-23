"""Four isolated accounts using real HTTP lobby requests. Never starts a game."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import tempfile
import threading

from lobby_client import api
from lobby_server import Directory, Handler


def simulate():
    report = {"type": "isolated_http_lobby_simulation", "accounts": 4,
              "time": datetime.now().astimezone().isoformat(), "game_processes_launched": 0,
              "scope": "Local HTTP directory only. No WAN, CGNAT or latency validation.", "steps": []}
    with tempfile.TemporaryDirectory(prefix="tm3_lobby_sim_") as folder:
        directory = Directory(Path(folder) / "users.sqlite3")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.directory = directory
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f"http://127.0.0.1:{server.server_port}"
        tokens = {}

        def request(name, op="poll", **kwargs):
            return api(url, dict(op=op, token=tokens[name], **kwargs))

        def snapshot(label):
            # Four independent clients poll the directory concurrently.
            with ThreadPoolExecutor(max_workers=4) as pool:
                states = dict(zip(tokens, pool.map(request, tokens)))
            signatures = [{(r["id"], tuple(r["players"]), r["phase"]) for r in state["rooms"]}
                          for state in states.values()]
            assert all(s == signatures[0] for s in signatures), "Las cuentas vieron listas distintas"
            views = {}
            for name, state in states.items():
                assert all(len(r["players"]) <= 2 for r in state["rooms"])
                views[name] = {"joined_host": state["room"]["host"] if state["room"] else None,
                               "rooms": [{"host": r["host"], "players": r["players"],
                                          "slots": f"{len(r['players'])}/{r['capacity']}",
                                          "phase": r["phase"], "joinable": r["joinable"]}
                                         for r in state["rooms"]]}
                for room in state["rooms"]:
                    if name not in room["players"]:
                        assert room["address"] is None, "Un observador recibio el destino del juego"
            report["steps"].append({"label": label, "views": views})
            return states

        try:
            for name in ("Nelson", "Oscar", "Sofia", "Alex"):
                tokens[name] = api(url, dict(op="login", name=name, secret=secrets.token_hex(32), lan="127.0.0.1"))["token"]
            snapshot("Cuatro cuentas conectadas; ninguna ha creado sala")
            room_a = request("Nelson", "create")["room"]["id"]
            states = snapshot("Nelson crea sala; las otras tres la ven sin unirse")
            assert all(states[n]["room"] is None for n in ("Oscar", "Sofia", "Alex"))
            room_b = request("Oscar", "create")["room"]["id"]
            states = snapshot("Oscar crea otra sala; Sofia y Alex ven ambas desde el lobby")
            assert all(states[n]["room"] is None for n in ("Sofia", "Alex"))
            request("Sofia", "join", room=room_a)
            states = snapshot("Sofia entra con Nelson; Alex ve esa sala llena y la de Oscar disponible")
            assert states["Alex"]["room"] is None
            try:
                request("Alex", "join", room=room_a)
                raise AssertionError("Se permitio un tercer jugador")
            except ValueError:
                report["third_player_rejected"] = True
            assert request("Alex")["room"] is None
            request("Alex", "join", room=room_b)
            snapshot("Dos salas independientes de dos jugadores: Nelson/Sofia y Oscar/Alex")
            try:
                request("Sofia", "start")
                raise AssertionError("Un invitado inicio la sala")
            except ValueError:
                report["guest_start_rejected"] = True
            generation = request("Nelson", "start")["room"]["generation"]
            request("Nelson", "ready", generation=generation)
            request("Sofia", "ready", generation=generation)
            states = snapshot("Start de Nelson solo prepara su sala; la de Oscar sigue esperando")
            assert states["Nelson"]["room"]["phase"] == "host"
            assert states["Oscar"]["room"]["phase"] == "waiting"
            # Simulate client acknowledgements only; there is no subprocess/game launch here.
            request("Nelson", "host_started", generation=generation)
            request("Sofia", "client_started", generation=generation)
            states = snapshot("Confirmaciones de arranque simuladas; segunda sala independiente")
            assert states["Nelson"]["room"]["phase"] == "playing"
            assert states["Oscar"]["room"]["phase"] == "waiting"
            request("Nelson", "leave")
            states = snapshot("Al salir Nelson desaparece su sala para todos; la de Oscar permanece")
            assert all([r["host"] for r in state["rooms"]] == ["Oscar"] for state in states.values())
            assert states["Sofia"]["room"] is None
            report["passed"] = True
        finally:
            for token in tokens.values():
                try:
                    api(url, dict(op="logout", token=token))
                except Exception:
                    pass
            server.shutdown()
            server.server_close()
            worker.join()
            directory.db.close()
    return report


def markdown(report):
    lines = ["# Simulacion de cuatro cuentas TM3", "", f"Fecha: {report['time']}", "",
             "Resultado: APROBADO. Cuatro cuentas aisladas y peticiones HTTP reales a un directorio temporal.", "",
             "No se abrio el juego. Las confirmaciones de arranque se simularon; no se probaron Internet, CGNAT ni latencia.", ""]
    for step in report["steps"]:
        lines += [f"## {step['label']}", "", "| Cuenta | Dentro de sala | Salas que ve |", "|---|---|---|"]
        for name, view in step["views"].items():
            rooms = "; ".join(f"{r['host']} {r['slots']} ({r['phase']})" for r in view["rooms"]) or "Ninguna"
            lines.append(f"| {name} | {view['joined_host'] or 'Solo lobby'} | {rooms} |")
        lines.append("")
    lines += ["Tercer jugador rechazado: SI. Start del invitado rechazado: SI.", "",
              "Los perfiles, tokens y la base de usuarios temporales no se conservan. El informe no contiene credenciales.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = simulate()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "simulation.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        (args.output / "README.md").write_text(markdown(result), encoding="utf-8")
    print(markdown(result))
