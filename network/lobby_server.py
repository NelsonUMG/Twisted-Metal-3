"""TM3 lobby directory. Standard library only; never carries game traffic."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import socket
import sqlite3
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from relay_protocol import endpoint, issue_ticket, validate_secret

PORT = 27890
ROOM_CAPACITY = 2
CHAT_HISTORY = 100
CHAT_MAX_LENGTH = 500
DISCOVERY = b"TM3_LOBBY_DISCOVER_V1"


def username(value):
    if not isinstance(value, str):
        raise ValueError("El nombre de usuario debe ser texto.")
    value = unicodedata.normalize("NFKC", value).strip()
    if not 2 <= len(value) <= 24 or not all(c.isalnum() or c in "_- " for c in value):
        raise ValueError("Usa de 2 a 24 letras, numeros, espacios, _ o -.")
    return value, value.casefold()


def room_description(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100 or any(ord(c) < 32 for c in value):
        raise ValueError("La descripción debe tener entre 1 y 100 caracteres, en una sola línea.")
    return value.strip()


class Directory:
    def __init__(self, database, relay_url=None, relay_secret=None, automatic_ice=False):
        if relay_url and automatic_ice:
            raise ValueError('Elige relay o ICE automático para este directorio, no ambos.')
        self.automatic_ice = automatic_ice
        self.relay_url = relay_url
        self.relay_secret = validate_secret(relay_secret) if relay_url else None
        if relay_url:
            endpoint(relay_url)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, display TEXT, secret TEXT)")
        self.sessions = {}
        self.rooms = {}

    def prune(self):
        now = time.monotonic()
        for token, session in list(self.sessions.items()):
            if now - session["seen"] > 20:
                self.leave(token)
                del self.sessions[token]
        for room in self.rooms.values():
            if room["phase"] in ("connect", "prepare", "host", "client") and now - room["since"] > (90 if room['phase'] == 'connect' else 25):
                room.update(phase="waiting", ice_signals={}, error="Se agoto el tiempo de inicio. Revisa ambos equipos.")

    def leave(self, token):
        for rid, room in list(self.rooms.items()):
            if room["owner"] == token:
                del self.rooms[rid]
            elif token in room["players"]:
                room["players"].remove(token)
                room.update(phase="waiting", ice_signals={}, error="El otro jugador salio.")
                self.message(room, "Sistema", f"{self.sessions[token]['name']} salió de la sala.", "system")

    def message(self, room, name, text, kind="text"):
        room["chat_seq"] += 1
        room["chat"].append(dict(id=room["chat_seq"], name=name, text=text, kind=kind, time=time.time()))
        del room["chat"][:-CHAT_HISTORY]

    def room_for(self, token):
        return next((r for r in self.rooms.values() if token in r["players"]), None)

    def public_room(self, room, token):
        owner = self.sessions[room["owner"]]
        peer = self.sessions[token]
        # A public directory learns WAN addresses from the connection, not user input.
        address = owner["lan"] if owner["ip"] == peer["ip"] or owner["ip"].startswith("127.") else owner["ip"]
        transport = None
        if self.automatic_ice and token in room['players'] and room['phase'] != 'waiting':
            transport = dict(mode='ice', generation=room['generation'])
            signals = room.get('ice_signals', {})
            name = 'answer' if token == room['owner'] else 'offer'
            if name in signals:
                transport[name] = signals[name]
        if (self.relay_url and token in room["players"] and
                room["phase"] in ("prepare", "host", "client", "playing")):
            transport = dict(mode="relay", protocol=1, url=self.relay_url,
                             ticket=issue_ticket(self.relay_secret, room["relay_session"],
                                                 0 if token == room["owner"] else 1))
        return {"id": room["id"], "host": owner["name"], "description": room["description"],
                "players": [self.sessions[t]["name"] for t in room["players"]],
                "phase": room["phase"], "owner": token == room["owner"],
                "capacity": ROOM_CAPACITY,
                "joinable": room["phase"] == "waiting" and len(room["players"]) < ROOM_CAPACITY,
                "address": address if token in room["players"] else None,
                "chat": list(room["chat"]) if token in room["players"] else [],
                "generation": room["generation"], "error": room["error"],
                "connection_mode": "ice" if self.automatic_ice else "relay" if self.relay_url else "direct", "transport": transport}

    def request(self, data, address):
        with self.lock:
            self.prune()
            op = data.get("op")
            if op == "login":
                name, key = username(data.get("name", ""))
                secret = str(data.get("secret", ""))
                if len(secret) != 64:
                    raise ValueError("Perfil invalido.")
                digest = hashlib.sha256(secret.encode()).hexdigest()
                row = self.db.execute("SELECT display, secret FROM users WHERE name=?", (key,)).fetchone()
                if row and not hmac.compare_digest(row[1], digest):
                    raise ValueError("Ese usuario ya existe. Elige otro nombre.")
                if any(s["key"] == key for s in self.sessions.values()):
                    raise ValueError("Ese usuario ya esta conectado.")
                if not row:
                    self.db.execute("INSERT INTO users VALUES (?,?,?)", (key, name, digest))
                    self.db.commit()
                token = secrets.token_hex(32)
                lan = str(data.get("lan", address))
                try:
                    socket.inet_pton(socket.AF_INET, lan)
                except OSError:
                    lan = address
                self.sessions[token] = dict(name=row[0] if row else name, key=key,
                                            ip=address, lan=lan, seen=time.monotonic(),
                                            relay_protocol=data.get("relay_protocol", 0))
                self.sessions[token]['automatic_ice'] = data.get('automatic_ice', 0)
                return {"token": token}
            token = str(data.get("token", ""))
            if token not in self.sessions:
                raise ValueError("Sesion vencida. Vuelve a conectar.")
            self.sessions[token]["seen"] = time.monotonic()
            room = self.room_for(token)
            if op == "create":
                if room:
                    raise ValueError("Ya estas en una sala.")
                description = room_description(data.get("description", f"Sala de {self.sessions[token]['name']}"))
                rid = secrets.token_hex(6)
                self.rooms[rid] = dict(id=rid, owner=token, players=[token], phase="waiting",
                                       generation=0, ready=[], error="", since=time.monotonic(), chat=[], chat_seq=0, description=description)
                self.message(self.rooms[rid], "Sistema", f"{self.sessions[token]['name']} creó la sala.", "system")
            elif op == "join":
                target = self.rooms.get(data.get("room"))
                if room or not target or len(target["players"]) >= ROOM_CAPACITY or target["phase"] != "waiting":
                    raise ValueError("La sala ya no esta disponible.")
                target["players"].append(token)
                target["error"] = ""
                self.message(target, "Sistema", f"{self.sessions[token]['name']} entró a la sala.", "system")
            elif op == "chat":
                text = data.get("text")
                if not room:
                    raise ValueError("Debes entrar a una sala para chatear.")
                if not isinstance(text, str) or not text.strip() or len(text) > CHAT_MAX_LENGTH:
                    raise ValueError("El mensaje debe tener entre 1 y 500 caracteres.")
                if any(ord(char) < 32 and char not in "\n\t" for char in text):
                    raise ValueError("El mensaje contiene caracteres no válidos.")
                self.message(room, self.sessions[token]["name"], text.strip())
            elif op == "leave":
                self.leave(token)
            elif op == "logout":
                self.leave(token)
                del self.sessions[token]
                return {}
            elif op == "cancel":
                if not room or data.get("generation") != room["generation"]:
                    raise ValueError("Inicio de partida vencido.")
                room.update(phase="waiting", ready=[], ice_signals={}, error="", since=time.monotonic())
            elif op == "start":
                if not room or room["owner"] != token or len(room["players"]) != ROOM_CAPACITY or room["phase"] != "waiting":
                    raise ValueError("Start requiere al anfitrion y dos jugadores en espera.")
                if self.relay_url and any(self.sessions[t]["relay_protocol"] != 1 for t in room["players"]):
                    raise ValueError("Actualiza TM3Lobby en ambas PC para conectar por Internet.")
                if self.automatic_ice and any(self.sessions[t]['automatic_ice'] != 1 for t in room['players']):
                    raise ValueError('Actualiza ambos lobbies para conectar automáticamente.')
                room.update(phase="connect" if self.automatic_ice else "prepare", ready=[], ice_ready=[], ice_signals={}, error="", since=time.monotonic(),
                            generation=room["generation"] + 1, relay_session=secrets.token_hex(24))
            elif op in ('ice_offer', 'ice_answer', 'ice_ready'):
                if not self.automatic_ice or not room or room['phase'] != 'connect' or data.get('generation') != room['generation']:
                    raise ValueError('Negociación de sala vencida.')
                if op == 'ice_ready':
                    if 'answer' not in room['ice_signals']:
                        raise ValueError('Falta la respuesta de conexión.')
                    if token not in room['ice_ready']:
                        room['ice_ready'].append(token)
                    if len(room['ice_ready']) == 2:
                        room.update(phase='prepare', ice_signals={}, since=time.monotonic())
                else:
                    kind = 'offer' if op == 'ice_offer' else 'answer'
                    if (kind == 'offer') != (token == room['owner']) or (kind == 'answer' and 'offer' not in room['ice_signals']):
                        raise ValueError('Negociación no autorizada.')
                    code = data.get('code')
                    if not isinstance(code, str) or len(code) > 32000 or not code.startswith('TM3ICE1.'):
                        raise ValueError('Señal de conexión inválida.')
                    previous = room['ice_signals'].get(kind)
                    if previous is not None and previous != code:
                        raise ValueError('La señal de conexión ya fue publicada.')
                    room['ice_signals'][kind] = code
            elif op in ("ready", "host_started", "client_started", "failed"):
                if not room or data.get("generation") != room["generation"]:
                    raise ValueError("Inicio de partida vencido.")
                if op == "failed":
                    if room["phase"] not in ("connect", "prepare", "host", "client"):
                        raise ValueError("El intento de inicio ya termino; se ignora el error tardio.")
                    room.update(phase="waiting", ice_signals={}, error=str(data.get("error", "No se pudo iniciar."))[:240])
                elif op == "ready" and room["phase"] == "prepare":
                    if token not in room["ready"]:
                        room["ready"].append(token)
                    if len(room["ready"]) == 2:
                        room.update(phase="host", since=time.monotonic())
                elif op == "host_started" and room["phase"] == "host" and token == room["owner"]:
                    room.update(phase="client", since=time.monotonic())
                elif op == "client_started" and room["phase"] == "client" and token != room["owner"]:
                    room["phase"] = "playing"
            elif op != "poll":
                raise ValueError("Operacion desconocida.")
            room = self.room_for(token)
            return {"rooms": [self.public_room(r, token) for r in self.rooms.values()],
                    "room": self.public_room(room, token) if room else None}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond(200, {"service": "TM3Lobby", "version": 2,
                           "relay_protocol": 1 if self.server.directory.relay_url else 0,
                           'automatic_ice': 1 if self.server.directory.automatic_ice else 0})

    def respond(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 36000:
                raise ValueError("Solicitud invalida.")
            self.connection.settimeout(5)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Solicitud invalida.")
            self.respond(200, self.server.directory.request(data, self.client_address[0]))
        except (ValueError, TypeError) as exc:
            self.respond(400, {"error": str(exc)})
        except (OSError, TimeoutError):
            pass

    def log_message(self, *_):
        pass  # Never log profile credentials or session tokens.


def serve_discovery(port, stop=None):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.bind(("0.0.0.0", PORT))
        except OSError:
            return
        sock.settimeout(.25)
        while stop is None or not stop.is_set():
            try:
                data, peer = sock.recvfrom(256)
            except socket.timeout:
                continue
            if data == DISCOVERY:
                sock.sendto(f"TM3_LOBBY_V1 {port}".encode(), peer)


class LocalDirectory:
    """Directory lifetime belongs to the GUI; no detached helper process."""
    def __init__(self, database, port=PORT):
        self.stop = threading.Event()
        self.server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        self.server.daemon_threads = True
        self.server.directory = Directory(database)
        self.threads = [threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .1}, daemon=True),
                        threading.Thread(target=serve_discovery, args=(port, self.stop), daemon=True)]
        for thread in self.threads:
            thread.start()

    def close(self):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        with self.server.directory.lock:
            self.server.directory.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--database", type=Path, default=Path(__file__).with_name("lobby_users.sqlite3"))
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--relay-url", default=os.environ.get("TM3_RELAY_URL"),
                        help="Public HTTPS /tm3-relay URL; requires TM3_RELAY_SECRET in the environment")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.daemon_threads = True
    server.directory = Directory(args.database, args.relay_url, os.environ.get("TM3_RELAY_SECRET"))
    if args.discover:
        threading.Thread(target=serve_discovery, args=(args.port,), daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
