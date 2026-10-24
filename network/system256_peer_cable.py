"""Single-console cable exchange transported over the authenticated P2P link.

The game still speaks the SYSTEM256 ABI-6 mailbox. Each PC owns one real core;
matching cable requests are exchanged through the lobby's encrypted WebRTC
DataChannel. The Cloudflare directory/STUN service never handles game bytes.
"""
import ctypes as C
import struct
import threading
import time
from collections import deque


HEADER = struct.Struct('!4sQBBHIIIII')
MAGIC = b'T3C1'
VERSION = 1
MAX_PAYLOAD = 64 * 1024
MAX_QUEUED_REMOTE = 32
GAMEPLAY_CALL = 0x8003AA98
# A real PS1 serial exchange has no wall-clock deadline. Online cable calls
# therefore wait until the peer reaches the matching request or the transport
# itself closes. A finite timeout remains injectable for isolated tests.
ROLE = struct.Struct('!4sQBI')


class PeerCable:
    """Synchronous ABI-6 cable endpoint for exactly one local console."""

    def __init__(self, side, epoch, send_packet, timeout=None):
        if side not in (0, 1) or not 0 < epoch < 2**64:
            raise ValueError('Invalid peer cable identity')
        self.side, self.epoch = side, epoch
        self.send_packet = send_packet
        self.timeout = timeout
        self.condition = threading.Condition()
        self.pending = None
        self.remote = {}
        self.ordinals = {}
        self.next_sequence = 0
        self.remote_sequence = 0
        self.error = None
        self.stopped = False
        self.exchanges = 0
        self.gameplay = 0
        self.match_active = False
        self.time_mismatches = 0
        self.rng_mismatches = 0
        self.last_tail = None
        self.bytes_sent = 0
        self.bytes_received = 0
        self.wait_ms = []
        self.observer = None
        self.role_round = 0
        self.remote_role_round = 0
        self.role_pending = None
        self.role_agreed = False
        self.role_events = deque(maxlen=64)
        self.role_observer = None

    def _role_event(self, event, **extra):
        value = dict(event=event, monotonic=round(time.monotonic(), 6),
                     side=self.side, local_round=self.role_round,
                     remote_round=self.remote_role_round)
        value.update(extra)
        self.role_events.append(value)
        if self.role_observer:
            self.role_observer(value)

    def check_role_timeout(self):
        """Keep the ABI polling hook without timing out a live role handshake.

        Transport closure still calls stop(), which fails the pending mailbox.
        The timeout configured on this object continues to protect ordinary
        synchronous cable exchanges in exchange().
        """
        return None

    def waiting_snapshot(self):
        """Return the current cable wait, distinguishing menus from gameplay."""
        with self.condition:
            if self.role_pending is not None and not self.role_agreed:
                return dict(phase='online_mode', call=None,
                            seconds=max(0.0, time.monotonic() - self.role_pending[1]))
            if self.pending is None or self.pending['done']:
                return None
            call = self.pending['call']
            phase = ('vehicle_selection' if call in (0x80047EA0, 0x80047EB8)
                     else 'cable_transfer')
            return dict(phase=phase, call=call,
                        seconds=max(0.0, time.monotonic() - self.pending['started']))

    def _finish_role(self):
        if self.role_pending and self.remote_role_round >= self.role_round:
            header, _started = self.role_pending
            struct.pack_into('<H', header, 10, 0x700 | (2 if self.side == 0 else 1))
            struct.pack_into('<I', header, 24, 0)
            struct.pack_into('<H', header, 6, 3)
            self.role_pending = None
            self.role_agreed = True
            self._role_event('role_completed', wait_seconds=round(time.monotonic() - _started, 3))

    def reset_role_cycle(self):
        """Require a fresh bilateral YES after returning to the main menu."""
        with self.condition:
            if not self.role_agreed or self.role_pending:
                return False
            self.role_agreed = False
            self.match_active = False
            self._role_event('role_cycle_reset')
            return True

    @staticmethod
    def _ranges(items, ram, size):
        result = []
        for address, length in items:
            if length < 0 or length > MAX_PAYLOAD:
                raise ValueError('Invalid cable memory range length')
            if address >> 28 not in (0, 8, 10) and length:
                raise ValueError(f'Invalid cable RAM address {address:#x}')
            offset = address & 0x0FFFFFFF
            if offset + length > size:
                raise ValueError('Cable memory range is outside emulated RAM')
            result.append((ram + offset, length))
        return result

    def _local_request(self, side, ram, size):
        if side != self.side or size != 256 * 1024 * 1024:
            raise ValueError('Cable endpoint does not match the local console')
        header = (C.c_ubyte * 112).from_address(ram + 0x47900)
        magic, version, status, command, _flags, _seq, send_n, recv_n, _recv_size, call = \
            struct.unpack_from('<I4H5I', header)
        if magic != 0x4F334D54 or version != 6 or status != 1:
            raise ValueError('Invalid SYSTEM256 cable mailbox')
        if send_n > MAX_PAYLOAD or recv_n > MAX_PAYLOAD:
            raise ValueError('SYSTEM256 cable request exceeds 64 KiB')
        if command == 1:
            with self.condition:
                if self.stopped:
                    raise RuntimeError(self.error or 'P2P cable stopped')
                # Role selection is a session handshake, not a lockstep game
                # operation. Menus may query it different numbers of times.
                if self.role_agreed:
                    struct.pack_into('<H', header, 10, 0x700 | (2 if self.side == 0 else 1))
                    struct.pack_into('<I', header, 24, 0)
                    struct.pack_into('<H', header, 6, 3)
                    self._role_event('role_reused')
                    return None
                self.role_round += 1
                self.role_pending = (header, time.monotonic())
                self._role_event('local_yes')
                self._finish_role()
            self.send_packet(ROLE.pack(b'T3R1', self.epoch, self.side, self.role_round))
            return None
        if call == GAMEPLAY_CALL:
            self.match_active = True
        if command == 2:
            send_address, recv_address = struct.unpack_from('<II', header, 32)
            sends = [(send_address, send_n)]
            receives = [(recv_address, recv_n)]
        elif command == 3:
            send_count, recv_count = struct.unpack_from('<II', header, 40)
            if send_count > 4 or recv_count > 4:
                raise ValueError('Invalid SYSTEM256 cable batch count')
            sends = [struct.unpack_from('<II', header, 48 + 8 * i)
                     for i in range(send_count)]
            receives = [struct.unpack_from('<II', header, 80 + 8 * i)
                        for i in range(recv_count)]
        else:
            raise ValueError(f'Unsupported SYSTEM256 cable command {command}')
        sends = self._ranges(sends, ram, size)
        receives = self._ranges(receives, ram, size)
        if sum(length for _pointer, length in sends) != send_n:
            raise ValueError('SYSTEM256 cable send ranges do not match mailbox')
        if sum(length for _pointer, length in receives) != recv_n:
            raise ValueError('SYSTEM256 cable receive ranges do not match mailbox')
        payload = b''.join(C.string_at(pointer, length) for pointer, length in sends)
        if len(payload) != send_n:
            raise ValueError('Could not copy SYSTEM256 cable payload')
        ordinal = self.ordinals.get(call, 0) + 1
        if ordinal >= 2**32:
            raise ValueError('SYSTEM256 cable ordinal exhausted')
        self.ordinals[call] = ordinal
        self.next_sequence += 1
        if self.next_sequence >= 2**32:
            raise ValueError('SYSTEM256 cable sequence exhausted')
        request = dict(command=command, call=call, ordinal=ordinal,
                       send_n=send_n, recv_n=recv_n, payload=payload,
                       receives=receives, header=header, done=False,
                       started=time.monotonic())
        request['wire'] = HEADER.pack(MAGIC, self.epoch, self.side, VERSION,
                                      command, self.next_sequence, ordinal,
                                      call, send_n, recv_n) + payload
        return request

    @staticmethod
    def _key(request):
        return (request['command'], request['call'], request['ordinal'])

    def exchange(self, side, ram, size):
        try:
            request = self._local_request(side, ram, size)
            if request is None:
                return
            with self.condition:
                if self.stopped:
                    raise RuntimeError(self.error or 'P2P cable stopped')
                if self.pending is not None:
                    raise RuntimeError('A second local cable request arrived before completion')
                self.pending = request
                remote = self.remote.pop(self._key(request), None)
                if remote is not None:
                    self._pair(request, remote)
            self.send_packet(request['wire'])
            self.bytes_sent += len(request['wire'])
            deadline = time.monotonic() + self.timeout if self.timeout is not None else None
            with self.condition:
                while not request['done'] and not self.stopped:
                    remaining = deadline - time.monotonic() if deadline is not None else None
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError(
                            f'P2P cable timeout: role={self.side} key={self._key(request)} '
                            f'wait_seconds={self.timeout} exchanges={self.exchanges} '
                            f'remote_sequence={self.remote_sequence} '
                            f'queued_remote_keys={list(self.remote)} '
                            f'bytes_sent={self.bytes_sent} bytes_received={self.bytes_received}')
                    self.condition.wait(min(remaining, 0.1) if remaining is not None else 0.1)
                if not request['done']:
                    raise RuntimeError(self.error or 'P2P cable stopped')
            self.wait_ms.append(round((time.monotonic() - request['started']) * 1000, 3))
        except BaseException as exc:
            self.stop(str(exc))
            try:
                struct.pack_into('<H', (C.c_ubyte * 112).from_address(ram + 0x47900), 6, 4)
            except (ValueError, OSError):
                pass

    def receive(self, packet):
        try:
            if isinstance(packet, bytes) and packet[:4] == b'T3R1':
                magic, epoch, side, round_number = ROLE.unpack(packet)
                if epoch != self.epoch or side != 1 - self.side or not round_number:
                    raise ValueError('Invalid P2P role envelope')
                with self.condition:
                    if self.stopped:
                        return
                    if round_number != self.remote_role_round + 1:
                        raise ValueError('Invalid P2P role sequence')
                    self.remote_role_round = round_number
                    self._role_event('remote_yes')
                    self._finish_role()
                return
            if not isinstance(packet, bytes) or len(packet) < HEADER.size:
                raise ValueError('Short P2P cable packet')
            magic, epoch, side, version, command, sequence, ordinal, call, send_n, recv_n = \
                HEADER.unpack_from(packet)
            payload = packet[HEADER.size:]
            if (magic != MAGIC or epoch != self.epoch or side != 1 - self.side or
                    version != VERSION or command not in (2, 3) or
                    send_n != len(payload) or send_n > MAX_PAYLOAD or
                    recv_n > MAX_PAYLOAD or not sequence or not ordinal):
                raise ValueError('Invalid P2P cable envelope')
            request = dict(command=command, call=call, ordinal=ordinal,
                           send_n=send_n, recv_n=recv_n, payload=payload,
                           sequence=sequence)
            with self.condition:
                if self.stopped:
                    return
                if sequence <= self.remote_sequence:
                    raise ValueError('Repeated or out-of-order P2P cable sequence')
                self.remote_sequence = sequence
                self.bytes_received += len(packet)
                key = self._key(request)
                if self.pending is not None and self._key(self.pending) == key:
                    self._pair(self.pending, request)
                else:
                    if len(self.remote) >= MAX_QUEUED_REMOTE:
                        raise ValueError('P2P cable queue limit exceeded')
                    if key in self.remote:
                        raise ValueError('Duplicate P2P cable request key')
                    self.remote[key] = request
        except BaseException as exc:
            self.stop(str(exc))

    def _pair(self, local, remote):
        if (local['command'], local['call'], local['ordinal']) != \
                (remote['command'], remote['call'], remote['ordinal']):
            raise ValueError('P2P cable request mismatch')
        if len(remote['payload']) > local['recv_n'] or len(local['payload']) > remote['recv_n']:
            raise ValueError('P2P cable payload does not fit the peer receive buffer')
        position = 0
        for pointer, length in local['receives']:
            count = min(length, len(remote['payload']) - position)
            if count > 0:
                C.memmove(pointer, remote['payload'][position:position + count], count)
            position += count
            if position == len(remote['payload']):
                break
        if position != len(remote['payload']):
            raise ValueError('P2P cable scatter operation was incomplete')
        struct.pack_into('<I', local['header'], 24, len(remote['payload']))
        struct.pack_into('<H', local['header'], 6, 3)
        local['done'] = True
        self.pending = None
        self.exchanges += 1
        if local['command'] == 3 and local['call'] == GAMEPLAY_CALL:
            self.gameplay += 1
            if len(local['payload']) >= 8 and len(remote['payload']) >= 8:
                local_tail = struct.unpack_from('<II', local['payload'], len(local['payload']) - 8)
                remote_tail = struct.unpack_from('<II', remote['payload'], len(remote['payload']) - 8)
                self.last_tail = (local_tail, remote_tail)
                self.time_mismatches += local_tail[0] != remote_tail[0]
                self.rng_mismatches += local_tail[1] != remote_tail[1]
            if self.observer:
                self.observer(self)
        self.condition.notify_all()

    def stop(self, error='P2P cable closed'):
        with self.condition:
            if not self.stopped:
                self.stopped = True
                self.error = error
                if self.role_pending is not None:
                    self._role_event('role_cancelled', reason=error)
                    struct.pack_into('<H', self.role_pending[0], 6, 4)
                    self.role_pending = None
                if self.pending is not None:
                    try:
                        struct.pack_into('<H', self.pending['header'], 6, 4)
                    except (ValueError, OSError):
                        pass
                self.condition.notify_all()

