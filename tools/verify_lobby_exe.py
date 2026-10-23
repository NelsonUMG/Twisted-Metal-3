"""Verify the frozen package with Python removed from child PATH; no game launched."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'network'))
from relay_client import open_tunnel
from relay_protocol import CONTROL, MAGIC, read_frame, write_frame


def api(url, data=None):
    request = Request(url, data=json.dumps(data, ensure_ascii=False).encode() if data else None,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=2) as reply:
        return json.load(reply)


def verify(package):
    exe = package / "TM3Lobby.exe"
    result = dict(game_processes_launched=0, python_removed_from_child_path=True)
    environment = {**os.environ, "PATH": str(Path(os.environ["SystemRoot"]) / "System32")}
    with tempfile.TemporaryDirectory(prefix="tm3_frozen_qa_") as folder:
        folder = Path(folder)
        environment["LOCALAPPDATA"] = str(folder)
        report = folder / "runtime_check.json"
        check = subprocess.run([str(exe), "--check-runtime", str(report)], env=environment, timeout=30)
        assert check.returncode == 0, "El ejecutable no pudo inicializarse"
        result["runtime"] = json.loads(report.read_text(encoding="utf-8"))
        assert result['runtime']['relay_protocol'] == 1
        assert result['runtime']['relay_bridge_available'] and result['runtime']['relay_tls_verified']
        assert result["runtime"]["frozen"] and result["runtime"]["gui_ok"] and result["runtime"]["chat_available"]
        assert "SqrtMergeV4" in result["runtime"]["variant"]
        if "SemiProduccion" in result["runtime"]["variant"]:
            assert result["runtime"]["local_button"] in ("Play locally", "Jugar local")
            assert result["runtime"]["diagnostics_enabled"] is False
            assert result["runtime"]["cpu_budget_percent"] == "175"
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            relay_port = reserve.getsockname()[1]
        relay_url = f'http://127.0.0.1:{relay_port}/tm3-relay'
        environment['TM3_RELAY_SECRET'] = secrets.token_hex(32)
        relay = subprocess.Popen([str(exe), '--relay-server', '--bind', '127.0.0.1', '--port', str(relay_port)], env=environment)
        service = subprocess.Popen([str(exe), "--lobby-server", "--bind", "127.0.0.1", "--port", str(port), "--database", str(folder / "users.sqlite3"), '--relay-url', relay_url], env=environment)
        url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    assert api(url)["service"] == "TM3Lobby"
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.1)
            tokens = [api(url, dict(op="login", name=name, secret=secrets.token_hex(32), lan="127.0.0.1", relay_protocol=1))["token"]
                      for name in ("Nelson QA", "Sofia QA", "Oscar QA", "Alex QA")]
            def request(index, op="poll", **kwargs):
                return api(url, dict(op=op, token=tokens[index], **kwargs))
            first = request(0, "create", description="Sala de prueba del EXE")["room"]
            request(2, "create", description="Otra sala del EXE")
            assert request(1)["room"] is None and len(request(1)["rooms"]) == 2
            request(1, "join", room=first["id"])
            request(0, "chat", text="Hola desde el ejecutable 🎮")
            assert request(1)["room"]["chat"][-1]["text"] == "Hola desde el ejecutable 🎮"
            assert all(r["chat"] == [] for r in request(3)["rooms"])
            host_route = request(0, 'start')['room']['transport']
            guest_route = request(1)['room']['transport']
            async def relay_check():
                deadline = time.monotonic() + 15
                while True:
                    try:
                        ar, aw = await open_tunnel(host_route['url'], host_route['ticket'])
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise
                        await asyncio.sleep(.1)
                br, bw = await open_tunnel(guest_route['url'], guest_route['ticket'])
                try:
                    control = CONTROL.pack(MAGIC, 7, 5, 0, 0, 42)
                    data = b'TM3O' + bytes(48) + b'frozen-qa'
                    await write_frame(aw, b'C', control)
                    assert await read_frame(br, 2) == (b'C', control)
                    await write_frame(bw, b'D', data)
                    assert await read_frame(ar, 2) == (b'D', data)
                finally:
                    aw.close(); bw.close()
                    await asyncio.gather(aw.wait_closed(), bw.wait_closed())
            asyncio.run(relay_check())
            result['frozen_relay'] = dict(signed_room_tickets=True, control=True, datagrams=True)
            for index in range(4):
                request(index, "logout")
            result["frozen_directory"] = dict(accounts=4, rooms_visible=2, description=True, chat_delivered=True, outsider_chat_hidden=True)
        finally:
            # Exact isolated helper launched above. Include its frozen bootloader child.
            for child in (service, relay):
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                child.wait(timeout=10)
    manifest = json.loads((package / "BUILD_MANIFEST.json").read_text(encoding="utf-8-sig"))
    for entry in manifest["files"]:
        if entry['file'] == 'TM3Lobby.json':
            continue  # The installed server URL/runtime settings are personal.
        path = package / entry["file"]
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        assert actual.upper() == entry["sha256"], f"Hash no coincide: {path}"
    result.update(manifest_verified=True, passed=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.package.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
