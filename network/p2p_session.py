"""ICE/STUN + DTLS/SCTP peer session. No hosted signaling service required.

Only data channels, never microphone/camera access. aiortc/aioice are pinned.
"""
from __future__ import annotations
import asyncio
from collections import OrderedDict, deque
import json
import queue
import secrets
import struct
import threading
import time
from aioice.stun import TransactionTimeout

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from p2p_codes import encode_description, decode_description
from relay_protocol import CONTROL, validate_game_frame

DEFAULT_ICE_SERVERS = [{'urls': 'stun:stun.cloudflare.com:3478'}]
MAX_BUFFER = 256 * 1024
GAME_BUFFER = 8 * 1024
PING_INTERVAL = 2
PING_STALE_SECONDS = 6


class LatencyTracker:
    """Bounded application RTT samples, measured with this PC's monotonic clock.

    The existing P/Q wire format remains compatible with earlier lobbies.
    Only echoes of our outstanding probes count; duplicates and arbitrary or
    expired timestamps cannot produce a displayed measurement.
    """
    def __init__(self):
        self.pending = OrderedDict()
        self.samples = deque(maxlen=30)
        self.last_sample_ns = None

    def probe(self, now_ns):
        while self.pending and (len(self.pending) >= 8 or now_ns - next(iter(self.pending)) > 10_000_000_000):
            self.pending.popitem(last=False)
        self.pending[now_ns] = now_ns
        return b'P' + struct.pack('!Q', now_ns)

    def echo(self, timestamp_ns, now_ns):
        sent = self.pending.pop(timestamp_ns, None)
        if sent is None or not 0 <= now_ns - sent <= 10_000_000_000:
            return False
        self.samples.append((now_ns - sent) / 1e6)
        self.last_sample_ns = now_ns
        return True

    def summary(self):
        values = list(self.samples)
        count = len(values)
        return dict(method='encrypted_control_echo', sample_window=30,
                    probe_interval_seconds=PING_INTERVAL, samples=count,
                    rtt_ms=values[-1] if values else None,
                    average_ms=sum(values) / count if count else None,
                    minimum_ms=min(values) if values else None,
                    maximum_ms=max(values) if values else None,
                    variation_ms=sum(abs(a - b) for a, b in zip(values, values[1:])) / (count - 1)
                    if count > 1 else (0.0 if count else None))


class DatagramOutbox:
    """Bounded, fair queue: coalesce exact native retries, never new fragments.

    NetBridge retries every 8 ms. Feeding every duplicate straight to SCTP
    creates seconds of stale backlog on WAN links. First sends are immediate;
    native retries remain unreliable, but cannot multiply inside this queue.
    """
    def __init__(self):
        self.pending = OrderedDict()
        self.history = OrderedDict()
        self.coalesced = self.expired = 0

    def offer(self, data, generation, now, retry_delay):
        key = (generation, data)
        previous = self.history.get(key)
        if key in self.pending or (previous is not None and now - previous < retry_delay):
            self.coalesced += 1
            return True
        if len(self.pending) >= 256:
            return False
        self.pending[key] = now
        return True

    def pop(self, generation, now):
        while self.pending:
            key, queued = self.pending.popitem(last=False)
            if key[0] != generation or now - queued > 1:
                self.expired += 1
                continue
            self.history[key] = now
            self.history.move_to_end(key)
            if len(self.history) > 512:
                self.history.popitem(last=False)
            return struct.pack('!I', key[0]) + key[1]
        return None

    def clear(self):
        self.pending.clear()
        self.history.clear()


class GameDatagrams(asyncio.DatagramProtocol):
    def __init__(self, bridge):
        self.bridge = bridge

    def datagram_received(self, data, address):
        b = self.bridge
        if address != b.target:
            return
        try:
            validate_game_frame(b'D', data)
            b.peer.send_datagram(data, b.generation)
        except ValueError:
            b.peer.dropped += 1

    def error_received(self, error):
        pass


class GameBridge:
    def __init__(self, peer, generation):
        self.peer = peer
        self.generation = generation
        self.target = None
        self.udp = self.writer = self.server = None
        self.tasks = []
        self.controls = asyncio.Queue(maxsize=64)
        self.local = asyncio.get_running_loop().create_future()
        self.closing = False

    async def start(self, host_port=None):
        loop = asyncio.get_running_loop()
        self.udp, _ = await loop.create_datagram_endpoint(lambda: GameDatagrams(self), local_addr=('127.0.0.1', 0))
        self.udp_port = self.udp.get_extra_info('sockname')[1]
        async def accept(reader, writer):
            if self.local.done():
                writer.close()
            else:
                self.local.set_result((reader, writer))
        if host_port is not None:
            self.local.set_result(await asyncio.wait_for(asyncio.open_connection('127.0.0.1', host_port), 3))
            port = host_port
        else:
            self.server = await asyncio.start_server(accept, '127.0.0.1', 0)
            port = self.server.sockets[0].getsockname()[1]
        self.tasks = [asyncio.create_task(self.local_controls()), asyncio.create_task(self.remote_controls())]
        for task in self.tasks:
            task.add_done_callback(self.task_finished)
        return port

    def task_finished(self, task):
        if task.cancelled() or self.closing:
            return
        error = task.exception()
        self.peer.emit('game_closed', type(error).__name__ if error else 'closed')

    async def local_controls(self):
        reader, self.writer = await asyncio.wait_for(asyncio.shield(self.local), 25)
        while True:
            data = await reader.readexactly(CONTROL.size)
            validate_game_frame(b'C', data)
            fields = CONTROL.unpack(data)
            if fields[2] in (1, 2):
                if not 0 < fields[3] < 65536:
                    raise ValueError('Invalid game UDP port')
                self.target = ('127.0.0.1', fields[3])
            await self.peer.send_reliable(b'C' + struct.pack('!I', self.generation) + data)

    async def remote_controls(self):
        _, writer = await asyncio.wait_for(asyncio.shield(self.local), 25)
        while True:
            data = await self.controls.get()
            fields = list(CONTROL.unpack(data))
            if fields[2] in (1, 2):
                fields[3] = self.udp_port
            writer.write(CONTROL.pack(*fields))
            await asyncio.wait_for(writer.drain(), 5)

    def receive(self, data):
        if self.target and self.udp:
            self.udp.sendto(data, self.target)

    async def close(self):
        self.closing = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.udp:
            self.udp.close()
        if self.server:
            self.server.close()
        if self.local.done() and not self.local.cancelled():
            _, writer = self.local.result()
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, TimeoutError):
                pass
        if self.server:
            await self.server.wait_closed()


class P2PSession:
    def __init__(self, ice_servers=None):
        self.ice_servers = DEFAULT_ICE_SERVERS if ice_servers is None else ice_servers
        self.events = queue.Queue(maxsize=512)
        self.ready = threading.Event()
        self.connected = threading.Event()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._thread, name='TM3ICE', daemon=True)
        self.error = ''
        self.game = None
        self.session = None
        self.expires = None
        self.invitation_deadline = None
        self.is_host = None
        self.sent = self.received = self.dropped = 0
        self.rtt_ms = None
        self.latency = LatencyTracker()
        # Publish an immutable-by-convention view; the Tk thread never waits
        # for network I/O or iterates the ICE loop's mutable sample deque.
        self._latency_view = (self.latency.summary(), None)
        self.connection_started = None
        self.remote_applied = False
        self.last_game_generation = 0
        self.pending_controls = []
        self.description_types = {}
        self.final_diagnostics = None
        self.outbox = DatagramOutbox()
        self.thread.start()
        if not self.ready.wait(5):
            raise ValueError('No se pudo iniciar ICE.')

    def _thread(self):
        try:
            asyncio.run(self._run())
        except Exception as exc:
            self.error = 'No se pudo iniciar ICE (' + type(exc).__name__ + ').'
            self.emit('error', self.error)
        finally:
            self.ready.set()
            self.connected.clear()
            self.done.set()

    async def _run(self):
        self.loop = asyncio.get_running_loop()
        self.stop = asyncio.Event()
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(**s) for s in self.ice_servers]))
        self.control = self.pc.createDataChannel('tm3-control-v1', negotiated=True, id=0, ordered=True)
        self.data = self.pc.createDataChannel('tm3-game-v1', negotiated=True, id=1, ordered=False, maxRetransmits=0)
        self.last_received = time.monotonic()
        self.channels_ready = asyncio.Event()
        self.outbox_ready = asyncio.Event()

        def opened():
            if self.control.readyState == self.data.readyState == 'open':
                self.connected.set()
                self.channels_ready.set()
                self.last_received = time.monotonic()
                self.emit('connected', self.diagnostics())
        self.control.on('open', opened)
        self.data.on('open', opened)
        self.control.on('message', self._control_message)
        self.data.on('message', self._data_message)
        self.control.on('close', lambda: self.fail('El otro equipo cerró la conexión P2P.'))

        @self.pc.on('connectionstatechange')
        async def changed():
            if self.pc.connectionState == 'failed':
                self.fail('ICE no encontró una ruta. Revisa UDP y el firewall; esta combinación de NAT puede necesitar un relay.')

        self.ready.set()
        watch = asyncio.create_task(self._watch())
        sender = asyncio.create_task(self._send_pending())
        try:
            await self.stop.wait()
        finally:
            watch.cancel()
            sender.cancel()
            await asyncio.gather(watch, sender, return_exceptions=True)
            self.final_diagnostics = self.diagnostics()
            if self.game:
                await self.game.close()
            await self.pc.close()

    def fail(self, reason):
        if not self.stop.is_set():
            self.error = reason
            self.emit('error', reason)
            self.stop.set()

    def emit(self, kind, value):
        try:
            self.events.put_nowait((kind, value))
        except queue.Full:
            self.error = 'Demasiados mensajes del otro equipo.'
            if hasattr(self, 'stop'):
                self.stop.set()

    def submit(self, coroutine, timeout=20):
        if self.done.is_set():
            coroutine.close()
            raise ValueError(self.error or 'La conexión ICE está cerrada.')
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout)
        except TimeoutError as exc:
            future.cancel()
            raise ValueError('Se agotó el tiempo de negociación ICE. Cierra e intenta de nuevo.') from exc

    def create_offer(self):
        return self.submit(self._offer())

    async def _offer(self):
        if self.session:
            raise ValueError('Esta invitación ya fue creada.')
        self.is_host = True
        self.invitation_deadline = time.monotonic() + 1800
        self.session, self.expires = secrets.token_hex(16), int(time.time()) + 1800
        await self.pc.sctp.transport.transport.iceGatherer.gather()
        self._manual_check_wait()
        await self.pc.setLocalDescription(await self.pc.createOffer())
        return self._code('offer')

    def create_answer(self, code):
        decoded = decode_description(code, 'offer')
        return self.submit(self._answer(decoded))

    async def _answer(self, value):
        if self.session:
            raise ValueError('Esta sesión ya fue iniciada.')
        self.session, self.expires = value['session'], value['expires']
        self.is_host = False
        self.invitation_deadline = time.monotonic() + 1800
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=value['sdp'], type='offer'))
        await self.pc.sctp.transport.transport.iceGatherer.gather()
        self._manual_check_wait()
        await self.pc.setLocalDescription(await self.pc.createAnswer())
        self.remote_applied = True
        self.connection_started = time.monotonic()
        return self._code('answer')

    def accept_answer(self, code):
        value = decode_description(code, 'answer', self.session)
        return self.submit(self._accept(value))

    async def _accept(self, value):
        if self.invitation_deadline is not None and time.monotonic() >= self.invitation_deadline:
            raise ValueError('La invitación agotó sus 30 minutos. Cierra y crea una nueva.')
        if not self.session or self.remote_applied or value['expires'] != self.expires:
            raise ValueError('La respuesta no corresponde a esta invitación.')
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=value['sdp'], type='answer'))
        self.remote_applied = True
        self.connection_started = time.monotonic()

    def _manual_check_wait(self):
        # Pinned aioice 0.10.2 adapter: preserve its authenticated STUN
        # transactions, but renew timed-out connectivity checks while a human
        # is still transferring the answer. No global library monkeypatch.
        connection = self.pc.sctp.transport.transport._connection
        for protocol in connection._protocols:
            original = protocol.request
            async def request(message, address, integrity_key=None, retransmissions=None, _original=original):
                if integrity_key is None or retransmissions is not None:
                    return await _original(message, address, integrity_key, retransmissions)
                while True:
                    remaining = (self.invitation_deadline or 0) - time.monotonic()
                    if remaining <= 0:
                        raise TransactionTimeout()
                    try:
                        async with asyncio.timeout(min(4, remaining)):
                            return await _original(message, address, integrity_key, retransmissions)
                    except TransactionTimeout:
                        if self.connected.is_set() or self.stop.is_set():
                            raise
                    except TimeoutError:
                        if self.connected.is_set() or self.stop.is_set() or time.monotonic() >= self.invitation_deadline:
                            raise TransactionTimeout() from None
            protocol.request = request

    def _code(self, kind):
        sdp = self.pc.localDescription.sdp
        self.description_types = {}
        for line in sdp.splitlines():
            if line.startswith('a=candidate:'):
                fields = line.split()
                candidate_type = fields[7]
                self.description_types[candidate_type] = self.description_types.get(candidate_type, 0) + 1
        return encode_description(sdp, kind, self.session, self.expires)

    async def send_reliable(self, data):
        await asyncio.wait_for(self.channels_ready.wait(), 5)
        async with asyncio.timeout(5):
            while self.control.bufferedAmount > MAX_BUFFER:
                await asyncio.sleep(.005)
        if self.control.readyState != 'open':
            raise ValueError('El canal de control está cerrado.')
        self.control.send(data)

    def send_message(self, message):
        encoded = json.dumps(message, separators=(',', ':'), ensure_ascii=False).encode()
        if len(encoded) > 2048:
            raise ValueError('Mensaje P2P demasiado grande.')
        self.submit(self.send_reliable(b'J' + encoded), 8)

    def _control_message(self, data):
        try:
            if not isinstance(data, bytes) or not 1 <= len(data) <= 2049:
                raise ValueError()
            self.last_received = time.monotonic()
            if data[:1] == b'C':
                if len(data) != 29:
                    raise ValueError()
                generation = struct.unpack('!I', data[1:5])[0]
                payload = data[5:]
                validate_game_frame(b'C', payload)
                if self.game and generation == self.game.generation:
                    self.game.controls.put_nowait(payload)
                elif generation == self.last_game_generation + 1 and len(self.pending_controls) < 64:
                    # The guest may send HELLO before the host attaches its
                    # local emulator. Preserve it, bounded and generation-scoped.
                    self.pending_controls.append((generation, payload))
                elif generation <= self.last_game_generation:
                    return  # Late controls from a retired game must not cross starts.
                else:
                    raise ValueError()
            elif data[:1] == b'J':
                value = json.loads(data[1:])
                if not isinstance(value, dict):
                    raise ValueError()
                self.events.put_nowait(('message', value))
            elif data[:1] == b'P' and len(data) == 9:
                self.control.send(b'Q' + data[1:])
            elif data[:1] == b'Q' and len(data) == 9:
                if self.latency.echo(struct.unpack('!Q', data[1:])[0], time.monotonic_ns()):
                    summary = self.latency.summary()
                    self.rtt_ms = summary['rtt_ms']
                    self._latency_view = (summary, self.latency.last_sample_ns)
            else:
                raise ValueError()
        except (ValueError, TypeError, asyncio.QueueFull, queue.Full):
            self.fail('El otro equipo envió un mensaje P2P inválido.')

    def send_datagram(self, data, generation):
        if self.data.readyState != 'open' or not self.game or self.game.generation != generation:
            self.dropped += 1
            return
        # Use only an observed application RTT, not private SCTP internals.
        retry_delay = max(.008, min(.25, (self.rtt_ms or 50) / 1000))
        if self.outbox.offer(bytes(data), generation, time.monotonic(), retry_delay):
            self.outbox_ready.set()
        else:
            self.dropped += 1

    async def _send_pending(self):
        while True:
            await self.outbox_ready.wait()
            self.outbox_ready.clear()
            while self.outbox.pending:
                if not self.game or self.data.readyState != 'open':
                    self.outbox.clear()
                    break
                if self.data.bufferedAmount >= GAME_BUFFER:
                    await asyncio.sleep(.002)
                    continue
                packet = self.outbox.pop(self.game.generation, time.monotonic())
                if packet is not None:
                    self.data.send(packet)
                    self.sent += 1

    def _data_message(self, data):
        try:
            if not isinstance(data, bytes) or len(data) < 4:
                raise ValueError()
            generation = struct.unpack('!I', data[:4])[0]
            payload = data[4:]
            validate_game_frame(b'D', payload)
        except (ValueError, TypeError, struct.error):
            self.dropped += 1
            return
        if self.game and self.game.generation == generation:
            self.game.receive(payload)
            self.received += 1
        self.last_received = time.monotonic()

    async def _watch(self):
        while not self.stop.is_set():
            await asyncio.sleep(PING_INTERVAL)
            now = time.monotonic()
            if self.connected.is_set():
                if now - self.last_received > 30:
                    self.fail('El otro equipo dejó de responder.')
                elif self.control.bufferedAmount < MAX_BUFFER:
                    self.control.send(self.latency.probe(time.monotonic_ns()))
            elif self.is_host and self.connection_started and now - self.connection_started > 60:
                self.fail('ICE no encontró una ruta directa en 60 segundos. Intercambia códigos nuevos o prueba un relay.')
            elif self.invitation_deadline and now > self.invitation_deadline:
                self.fail('La invitación agotó sus 30 minutos. Crea una nueva.')

    def attach_game(self, host_port=None, generation=None):
        return self.submit(self._attach_game(host_port, generation), 8)

    async def _attach_game(self, host_port, generation):
        if not self.connected.is_set():
            raise ValueError('Conecta las dos PC antes de iniciar el juego.')
        generation = self.last_game_generation + 1 if generation is None else generation
        if type(generation) is not int or not self.last_game_generation < generation <= 2147483647:
            raise ValueError('Intento de partida ICE vencido.')
        if self.game:
            await self.game.close()
        self.outbox.clear()
        self.game = GameBridge(self, generation)
        self.last_game_generation = generation
        port = await self.game.start(host_port)
        for pending_generation, payload in self.pending_controls:
            if pending_generation == generation:
                self.game.controls.put_nowait(payload)
        self.pending_controls.clear()
        return port

    def detach_game(self):
        async def detach():
            if self.game:
                await self.game.close()
                self.game = None
            self.outbox.clear()
        if not self.done.is_set():
            self.submit(detach(), 5)

    def latency_snapshot(self):
        """Nonblocking, secret-free view suitable for the UI thread."""
        summary, updated = self._latency_view
        age = max(0, (time.monotonic_ns() - updated) / 1e9) if updated is not None else None
        connected = self.connected.is_set() and not self.done.is_set()
        return dict(summary, age_seconds=age, connected=connected,
                    stale=not connected or age is None or age >= PING_STALE_SECONDS)

    def diagnostics(self):
        selected = {}
        # Observational only. aioice 0.10.2 exposes no public nominated-pair API.
        # Never depend on these private attributes for connection or routing.
        try:
            connection = self.pc.sctp.transport.transport._connection
            for pair in connection._nominated.values():
                selected = dict(local_type=pair.local_candidate.type, remote_type=pair.remote_candidate.type,
                                ip_version=6 if ':' in pair.local_candidate.host else 4)
        except (AttributeError, TypeError):
            pass
        return dict(version='ice_p2p_v1', ice_state=self.pc.iceConnectionState,
                    clock_independent_expiry=True, role='host' if self.is_host else 'guest',
                    remote_description_applied=self.remote_applied,
                    local_description_type=getattr(self.pc.localDescription, 'type', None),
                    remote_description_type=getattr(self.pc.remoteDescription, 'type', None),
                    connection_state=self.pc.connectionState, candidates=dict(self.description_types),
                    selected=selected, rtt_ms=self.rtt_ms, latency=self.latency_snapshot(), sent=self.sent, received=self.received,
                    dropped=self.dropped, coalesced=self.outbox.coalesced,
                    expired=self.outbox.expired, pending=len(self.outbox.pending), error=self.error)

    def snapshot(self):
        async def read():
            return self.diagnostics()
        if self.done.is_set():
            return {**(self.final_diagnostics or {}), 'latency': self.latency_snapshot(),
                    'error': self.error, 'closed': True}
        return self.submit(read(), 3)

    def close(self):
        if not self.done.is_set():
            self.loop.call_soon_threadsafe(self.stop.set)
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=5)
