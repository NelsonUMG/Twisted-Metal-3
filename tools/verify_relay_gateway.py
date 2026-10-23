"""Real Caddy HTTPS gateway + public directory + authenticated relay on loopback.

No DNS changes, public listeners or permanent trust-store modifications.
"""
import asyncio
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import tempfile
import threading
from urllib.request import Request, urlopen

from verify_linked_startup import TestRelay, listening, wait_for
from lobby_server import Directory, Handler
from relay_client import open_tunnel
from relay_protocol import CONTROL, MAGIC, read_frame, write_frame

ROOT = Path(__file__).resolve().parent.parent


def main():
    caddy = ROOT / 'diagnostics/internet_relay_v1/tools/caddy/caddy.exe'
    openssl = Path('C:/Program Files/Git/usr/bin/openssl.exe')
    relay = TestRelay()
    process = directory = server = thread = None
    try:
        with tempfile.TemporaryDirectory(prefix='tm3_gateway_qa_') as folder:
            base = Path(folder)
            cert, key = base/'cert.pem', base/'key.pem'
            subprocess.run([str(openssl), 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
                '-out', str(cert), '-days', '1', '-subj', '/CN=TM3GatewayQA', '-addext', 'subjectAltName=IP:127.0.0.1'],
                check=True, capture_output=True)
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0))
                port = reserve.getsockname()[1]
            url = f'https://127.0.0.1:{port}'
            directory = Directory(':memory:', url+'/tm3-relay', relay.secret)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.daemon_threads = True
            server.directory = directory
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
            thread.start()
            config = base/'Caddyfile'
            config.write_text('''{
    admin off
    auto_https off
}
https://127.0.0.1:PORT {
    bind 127.0.0.1
    tls "CERT" "KEY"
    handle /tm3-relay {
        reverse_proxy 127.0.0.1:RELAY
    }
    handle {
        reverse_proxy 127.0.0.1:DIRECTORY
    }
}
'''.replace('PORT', str(port)).replace('CERT', cert.as_posix()).replace('KEY', key.as_posix())
                .replace('RELAY', str(relay.port)).replace('DIRECTORY', str(server.server_port)), encoding='utf-8')
            trusted = ssl.create_default_context(cafile=str(cert))
            with (base/'caddy.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen([str(caddy), 'run', '--config', str(config), '--adapter', 'caddyfile'],
                    stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
                wait_for(lambda: listening(process.pid, port) or process.poll() is not None, 5, 'Caddy did not start')
                if process.poll() is not None:
                    raise RuntimeError((base/'caddy.log').read_text())
                def api(data=None):
                    request = Request(url, data=json.dumps(data).encode() if data else None,
                                      headers={'Content-Type': 'application/json'})
                    with urlopen(request, context=trusted, timeout=4) as response:
                        return json.load(response)
                assert api()['relay_protocol'] == 1
                def login(name):
                    return api(dict(op='login', name=name, secret=secrets.token_hex(32), relay_protocol=1))['token']
                host, guest = login('HostQA'), login('GuestQA')
                room = api(dict(op='create', token=host))['room']
                api(dict(op='join', token=guest, room=room['id']))
                host_route = api(dict(op='start', token=host))['room']['transport']
                guest_route = api(dict(op='poll', token=guest))['room']['transport']
                async def exchange():
                    ar, aw = await open_tunnel(host_route['url'], host_route['ticket'], trusted)
                    br, bw = await open_tunnel(guest_route['url'], guest_route['ticket'], trusted)
                    try:
                        control = CONTROL.pack(MAGIC, 7, 5, 0, 0, 42)
                        data = b'TM3O' + bytes(48) + b'gateway-udp'
                        await write_frame(aw, b'C', control)
                        assert await read_frame(br, 2) == (b'C', control)
                        await write_frame(bw, b'D', data)
                        assert await read_frame(ar, 2) == (b'D', data)
                    finally:
                        aw.close(); bw.close()
                        await asyncio.gather(aw.wait_closed(), bw.wait_closed())
                asyncio.run(exchange())
                print('PASS: real Caddy HTTPS gateway serves the directory and upgrades the same TLS port to the relay; ticketed control/datagram exchange works.')
                process.terminate()
                process.wait(timeout=5)
    finally:
        if process and process.poll() is None:
            process.terminate(); process.wait(timeout=5)
        if server:
            server.shutdown(); server.server_close()
        if thread:
            thread.join(timeout=2)
        if directory:
            directory.db.close()
        relay.close()


if __name__ == '__main__':
    main()
