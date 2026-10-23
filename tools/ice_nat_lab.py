"""Test-only, user-space IPv4/UDP network. Never imported by the shipped lobby.

Two isolated private networks, optionally nested behind carrier NATs. Only the
aioice UDP socket is virtualized: ICE, STUN transactions, DTLS, SCTP, data
channels and the production P2PSession / local game bridge are unchanged.
No host socket, router, adapter, route or firewall setting is modified.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
import random
import threading
from unittest.mock import patch

import aioice.ice
from aioice import stun

from p2p_session import P2PSession

STUN_ADDRESS = ('192.0.2.1', 3478)
PRIVATE_IPS = ('10.71.0.2', '10.82.0.2')
PUBLIC_IPS = ('198.51.100.10', '203.0.113.20')


@dataclass(frozen=True)
class NatPolicy:
    mapping: str = 'endpoint-independent'
    filtering: str = 'address-port-dependent'

    def __post_init__(self):
        if self.mapping not in ('endpoint-independent', 'address-port-dependent'):
            raise ValueError('Unsupported simulated NAT mapping')
        if self.filtering not in ('endpoint-independent', 'address-dependent', 'address-port-dependent'):
            raise ValueError('Unsupported simulated NAT filtering')


@dataclass
class Mapping:
    router: object
    internal: tuple
    external: tuple
    allowed: set = field(default_factory=set)


class Router:
    def __init__(self, network, address, policy, public):
        self.network, self.address, self.policy, self.public = network, address, policy, public
        self.mappings = {}

    def outbound(self, source, destination):
        key = (source,) if self.policy.mapping == 'endpoint-independent' else (source, destination)
        mapping = self.mappings.get(key)
        if mapping is None:
            external = (self.address, 42000 + len(self.mappings))
            mapping = self.mappings[key] = Mapping(self, source, external)
            self.network.mappings[external] = mapping
        mapping.allowed.add(destination)
        self.network.counts['nat_outbound_translations'] += 1
        return mapping.external

    def permits(self, mapping, source):
        if self.policy.filtering == 'endpoint-independent':
            return True
        if self.policy.filtering == 'address-dependent':
            return any(address[0] == source[0] for address in mapping.allowed)
        return source in mapping.allowed


class VirtualUDP(asyncio.DatagramTransport):
    def __init__(self, network, side, loop, protocol):
        self.network, self.side, self.loop, self.protocol = network, side, loop, protocol
        self.address = (PRIVATE_IPS[side], 31000 + side)
        self.closed = False

    def get_extra_info(self, name, default=None):
        # Returning no socket deliberately avoids altering any real OS socket.
        return self.address if name == 'sockname' else default

    def sendto(self, data, addr=None):
        if not self.closed:
            self.network.send(self, bytes(data), tuple(addr))

    def is_closing(self):
        return self.closed

    def close(self):
        if not self.closed:
            self.closed = True
            self.loop.call_soon(self.protocol.connection_lost, None)

    abort = close


class NatNetwork:
    def __init__(self, policies=None, depth=2, latency_ms=10, jitter_ms=0,
                 loss=0, block_peer_udp=False, seed=1701):
        if not 0 <= loss < 1 or latency_ms < jitter_ms or jitter_ms < 0 or depth not in (1, 2):
            raise ValueError('Invalid simulated link settings')
        policies = policies or (NatPolicy(), NatPolicy())
        self.policies, self.depth = policies, depth
        self.latency_ms, self.jitter_ms, self.loss = latency_ms, jitter_ms, loss
        self.block_peer_udp = block_peer_udp
        self.random = random.Random(seed)
        self.lock = threading.RLock()
        self.counts = Counter()
        self.endpoints, self.mappings = {}, {}
        self.routers = []
        for side, policy in enumerate(policies):
            chain = []
            if depth == 2:
                chain.append(Router(self, f'100.64.{side + 1}.5', policy, False))
            chain.append(Router(self, PUBLIC_IPS[side], policy, True))
            self.routers.append(chain)

    def endpoint(self, side, loop, protocol):
        with self.lock:
            endpoint = VirtualUDP(self, side, loop, protocol)
            if endpoint.address in self.endpoints:
                raise AssertionError('More than one ICE UDP endpoint per simulated PC')
            self.endpoints[endpoint.address] = endpoint
            protocol.connection_made(endpoint)
            return endpoint

    def _delay(self):
        return (self.latency_ms + self.random.uniform(-self.jitter_ms, self.jitter_ms)) / 1000

    @staticmethod
    def _schedule(endpoint, delay, callback, *args):
        def schedule():
            if not endpoint.closed:
                endpoint.loop.call_later(delay, callback, *args)
        try:
            endpoint.loop.call_soon_threadsafe(schedule)
        except RuntimeError:
            pass  # Peer loop was closed while a packet was in flight.

    def send(self, endpoint, data, destination):
        with self.lock:
            self.counts['outbound_packets'] += 1
            source = endpoint.address
            for router in self.routers[endpoint.side]:
                source = router.outbound(source, destination)
            if self.random.random() < self.loss:
                self.counts['random_loss'] += 1
                return
            if destination == STUN_ADDRESS:
                self._stun(endpoint, data, source)
                return
            # Both private LANs and the 100.64/10 carrier internals are NOT
            # reachable from the simulated Internet. Never use a direct path.
            mapping = self.mappings.get(destination)
            if mapping is None or not mapping.router.public:
                self.counts['unroutable_destination'] += 1
                return
            if self.block_peer_udp:
                self.counts['peer_udp_blocked'] += 1
                return
            target = self._target(mapping)
            if target is None:
                self.counts['unroutable_destination'] += 1
                return
            self._schedule(target, self._delay(), self._incoming, data, source, destination, False)

    def _target(self, mapping):
        while mapping.internal in self.mappings:
            mapping = self.mappings[mapping.internal]
        return self.endpoints.get(mapping.internal)

    def _stun(self, endpoint, data, source):
        try:
            request = stun.parse_message(data)
        except ValueError:
            self.counts['bad_stun'] += 1
            return
        if request.message_method != stun.Method.BINDING or request.message_class != stun.Class.REQUEST:
            self.counts['bad_stun'] += 1
            return
        self.counts['stun_requests'] += 1
        response = stun.Message(message_method=stun.Method.BINDING,
                                message_class=stun.Class.RESPONSE, transaction_id=request.transaction_id)
        response.attributes['XOR-MAPPED-ADDRESS'] = source
        if self.random.random() < self.loss:
            self.counts['random_loss'] += 1
            return
        self._schedule(endpoint, 2 * self._delay(), self._incoming,
                       bytes(response), STUN_ADDRESS, source, True)

    def _incoming(self, data, source, destination, from_stun):
        with self.lock:
            mapping = self.mappings[destination]
            while True:
                if not mapping.router.permits(mapping, source):
                    self.counts['nat_filter_dropped'] += 1
                    return
                self.counts['nat_inbound_translations'] += 1
                destination = mapping.internal
                if destination not in self.mappings:
                    break
                mapping = self.mappings[destination]
            endpoint = self.endpoints.get(destination)
            if endpoint is None or endpoint.closed:
                return
            self.counts['stun_delivered' if from_stun else 'peer_delivered'] += 1
            if not from_stun and data and 20 <= data[0] <= 63:
                # RFC 7983: DTLS records (SCTP and native game data are inside).
                self.counts['dtls_delivered'] += 1
            endpoint.protocol.datagram_received(data, source)

    def snapshot(self):
        with self.lock:
            return dict(depth_per_pc=self.depth,
                        policies=[dict(mapping=p.mapping, filtering=p.filtering) for p in self.policies],
                        one_way_latency_ms=self.latency_ms, jitter_ms=self.jitter_ms,
                        random_loss=self.loss, block_peer_udp=self.block_peer_udp,
                        counters=dict(self.counts),
                        mapping_counts=[[len(router.mappings) for router in chain] for chain in self.routers])


class SimulatedP2PSession(P2PSession):
    def __init__(self, network, side):
        self.simulation, self.side = network, side
        super().__init__(ice_servers=[{'urls': 'stun:192.0.2.1:3478'}])

    async def _run(self):
        loop = asyncio.get_running_loop()
        loop._tm3_nat_side = self.side
        original = loop.create_datagram_endpoint

        async def endpoint(factory, *args, **kwargs):
            protocol = factory()
            if isinstance(protocol, aioice.ice.StunProtocol):
                assert kwargs.get('local_addr') == (PRIVATE_IPS[self.side], 0)
                transport = self.simulation.endpoint(self.side, loop, protocol)
                return transport, protocol
            # Production GameBridge uses real loopback sockets, not this shim.
            return await original(lambda: protocol, *args, **kwargs)

        loop.create_datagram_endpoint = endpoint
        try:
            await super()._run()
        finally:
            loop.create_datagram_endpoint = original
            del loop._tm3_nat_side

    def selected_path(self):
        async def read():
            connection = self.pc.sctp.transport.transport._connection
            return [dict(local=list(pair.local_addr), remote=list(pair.remote_addr),
                         local_type=pair.local_candidate.type, remote_type=pair.remote_candidate.type)
                    for pair in connection._nominated.values()]
        return self.submit(read())


def isolated_ice_addresses():
    """Patch discovery ONLY for the two test event loops, not live lobby PCs."""
    original = aioice.ice.get_host_addresses

    def addresses(use_ipv4, use_ipv6):
        loop = asyncio.get_running_loop()
        side = getattr(loop, '_tm3_nat_side', None)
        if side is None:
            return original(use_ipv4, use_ipv6)
        return [PRIVATE_IPS[side]] if use_ipv4 else []

    return patch('aioice.ice.get_host_addresses', new=addresses)
