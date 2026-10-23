"""TLS WebSocket RPC for the shared room directory (never game traffic)."""
import json
from urllib.parse import urlsplit, urlunsplit

from relay_protocol import loopback


class WorkerDirectory:
    def __init__(self, url):
        from websockets.sync.client import connect
        parsed = urlsplit(url)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Dirección de directorio inválida.')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and loopback(parsed.hostname)):
            raise ValueError('El directorio de Internet requiere HTTPS.')
        address = urlunsplit(('wss' if parsed.scheme == 'https' else 'ws', parsed.netloc,
                              parsed.path.rstrip('/') + '/ws', '', ''))
        self.socket = connect(address, open_timeout=8, close_timeout=1, max_size=1024*1024,
                              compression=None, ping_interval=20, ping_timeout=20,
                              user_agent_header='TM3Lobby/3')
        self.serial = 0

    def request(self, data):
        self.serial += 1
        self.socket.send(json.dumps(dict(id=self.serial, data=data), separators=(',', ':')))
        value = json.loads(self.socket.recv(timeout=8))
        if not isinstance(value, dict) or value.get('id') != self.serial:
            raise ValueError('Respuesta inesperada del directorio.')
        if 'error' in value:
            raise ValueError(str(value['error'])[:240])
        if not isinstance(value.get('result'), dict):
            raise ValueError('Respuesta inválida del directorio.')
        return value['result']

    def close(self):
        self.socket.close()
