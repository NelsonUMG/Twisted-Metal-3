"""Authenticated local IPC for the confirmed-input engine; no NAT simulator."""
import asyncio
from collections import OrderedDict, deque
import hashlib
from multiprocessing.connection import Listener
import secrets
import struct
import threading
import time

from p2p_session import P2PSession, GAME_BUFFER

CABLE_PACKET_MAX = 36 + 64 * 1024
CABLE_FRAGMENT_MAX = 1800
CABLE_FRAGMENT_HEADER = struct.Struct('!4sIIHHI')
CABLE_FRAGMENT_MAGIC = b'S3CF'
ENGINE_IPC_MAX = CABLE_PACKET_MAX + 1


class System256Peer(P2PSession):
    def __init__(self, *args, **kwargs):
        self.engine_bridge = None
        self.engine_pending = deque(maxlen=128)
        self.engine_generation = None
        self.cable_send_sequence = 0
        self.cable_receive_sequence = 0
        self.cable_fragments = OrderedDict()
        super().__init__(*args, **kwargs)

    def deliver_engine(self, packet):
        if self.engine_bridge:
            self.engine_bridge.deliver(packet)
        elif len(self.engine_pending) < 128:
            self.engine_pending.append(packet)
        else:
            self.fail('Se desbordó la preparación del motor nuevo.')

    def _data_message(self, data):
        if isinstance(data, bytes) and data.startswith(b'T3I1') and len(data) <= 512:
            self.last_received = time.monotonic()
            self.deliver_engine(b'D' + data)
        else:
            super()._data_message(data)

    def _control_message(self, data):
        if isinstance(data, bytes) and data.startswith(CABLE_FRAGMENT_MAGIC):
            self._cable_fragment(data)
            return
        # Dedicated reliable envelope, separate from legacy cable controls.
        if isinstance(data, bytes) and data.startswith(b'S256') and len(data) <= 2048:
            self.last_received = time.monotonic()
            self.deliver_engine(b'M' + data[4:])
        else:
            super()._control_message(data)

    def _cable_fragment(self, data):
        try:
            if len(data) <= CABLE_FRAGMENT_HEADER.size:
                raise ValueError('P2P cable fragment is empty')
            magic, generation, sequence, index, count, total = CABLE_FRAGMENT_HEADER.unpack_from(data)
            fragment = data[CABLE_FRAGMENT_HEADER.size:]
            if (magic != CABLE_FRAGMENT_MAGIC or generation != self.engine_generation or
                    not sequence or not count or count > 64 or index >= count or
                    not 1 <= total <= CABLE_PACKET_MAX or len(fragment) > CABLE_FRAGMENT_MAX):
                raise ValueError('Invalid P2P cable fragment header')
            expected_count = (total + CABLE_FRAGMENT_MAX - 1) // CABLE_FRAGMENT_MAX
            expected_length = min(CABLE_FRAGMENT_MAX, total - index * CABLE_FRAGMENT_MAX)
            if count != expected_count or len(fragment) != expected_length:
                raise ValueError('Invalid P2P cable fragment size')
            state = self.cable_fragments.get(sequence)
            if state is None:
                if sequence != self.cable_receive_sequence + 1 or len(self.cable_fragments) >= 8:
                    raise ValueError('Stale or excessive P2P cable fragments')
                state = {'total': total, 'count': count, 'parts': {}, 'size': 0}
                self.cable_fragments[sequence] = state
            if state['total'] != total or state['count'] != count:
                raise ValueError('Conflicting P2P cable fragment metadata')
            previous = state['parts'].get(index)
            if previous is not None:
                if previous != fragment:
                    raise ValueError('Conflicting duplicate P2P cable fragment')
                return
            state['parts'][index] = fragment
            state['size'] += len(fragment)
            if len(state['parts']) == count:
                if state['size'] != total:
                    raise ValueError('Incomplete P2P cable message')
                packet = b''.join(state['parts'][part] for part in range(count))
                del self.cable_fragments[sequence]
                self.cable_receive_sequence = sequence
                self.last_received = time.monotonic()
                self.deliver_engine(b'C' + packet)
        except (ValueError, KeyError, TypeError):
            self.fail('El otro equipo envió datos de cable P2P inválidos.')


class EngineBridge:
    def __init__(self, peer, generation):
        self.peer = peer
        self.generation = generation
        self.epoch = int.from_bytes(hashlib.sha256(
            f'{peer.session}:{generation}:SYSTEM256'.encode()).digest()[:8], 'big') or 1
        peer.engine_generation = generation
        peer.cable_send_sequence = 0
        peer.cable_receive_sequence = 0
        peer.cable_fragments.clear()
        self.key = secrets.token_bytes(32)
        self.listener = Listener(('127.0.0.1', 0), authkey=self.key)
        self.port = self.listener.address[1]
        self.connection = None
        self.lock = threading.Lock()
        self.pending = deque(maxlen=128)
        self.closed = threading.Event()
        self.error = None
        peer.engine_bridge = self
        while peer.engine_pending:
            self.pending.append(peer.engine_pending.popleft())
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def deliver(self, packet):
        with self.lock:
            if self.closed.is_set():
                return
            if self.connection is None:
                if len(self.pending) == 128:
                    self.error = 'Engine preparation queue full'
                    self.closed.set()
                else:
                    self.pending.append(packet)
            else:
                try:
                    self.connection.send_bytes(packet)
                except (OSError, EOFError) as exc:
                    self.error = str(exc)
                    self.closed.set()

    def run(self):
        try:
            connection = self.listener.accept()
            with self.lock:
                if self.closed.is_set():
                    connection.close()
                    return
                self.connection = connection
                while self.pending:
                    connection.send_bytes(self.pending.popleft())
            while not self.closed.is_set():
                packet = connection.recv_bytes(ENGINE_IPC_MAX)
                if packet[:1] == b'M':
                    if len(packet) > 2049:
                        raise ValueError('Oversized engine control packet')
                    self.peer.submit(self.peer.send_reliable(b'S256' + packet[1:]), 8)
                elif packet[:5] == b'DT3I1' and len(packet) <= 513:
                    payload = packet[1:]
                    def send(payload=payload):
                        if self.peer.data.readyState == 'open' and self.peer.data.bufferedAmount < GAME_BUFFER:
                            self.peer.data.send(payload)
                    self.peer.loop.call_soon_threadsafe(send)
                elif packet[:1] == b'C' and 1 < len(packet) <= ENGINE_IPC_MAX:
                    self.peer.submit(self.send_cable(packet[1:]), 30)
                else:
                    raise ValueError('Invalid engine IPC packet')
        except (OSError, EOFError, ValueError) as exc:
            if not self.closed.is_set():
                self.error = str(exc)
        finally:
            self.closed.set()
            self.listener.close()
            if self.connection:
                self.connection.close()

    async def send_cable(self, packet):
        if not isinstance(packet, bytes) or not 1 <= len(packet) <= CABLE_PACKET_MAX:
            raise ValueError('Invalid engine cable packet size')
        self.peer.cable_send_sequence += 1
        sequence = self.peer.cable_send_sequence
        count = (len(packet) + CABLE_FRAGMENT_MAX - 1) // CABLE_FRAGMENT_MAX
        for index in range(count):
            fragment = packet[index * CABLE_FRAGMENT_MAX:(index + 1) * CABLE_FRAGMENT_MAX]
            envelope = CABLE_FRAGMENT_HEADER.pack(CABLE_FRAGMENT_MAGIC,
                self.generation, sequence, index, count, len(packet)) + fragment
            await self.peer.send_reliable(envelope)

    def close(self):
        self.closed.set()
        if self.peer.engine_bridge is self:
            self.peer.engine_bridge = None
        if self.connection:
            self.connection.close()
        self.listener.close()
