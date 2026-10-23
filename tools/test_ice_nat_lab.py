"""Check the simulator's isolation / mapping / filtering rules independently."""
import asyncio
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'network'))
sys.path.insert(0, str(ROOT / 'tools'))
from aioice import stun
from ice_nat_lab import NatNetwork, NatPolicy, PUBLIC_IPS, STUN_ADDRESS


class Sink(asyncio.DatagramProtocol):
    def __init__(self):
        self.received = []

    def datagram_received(self, data, address):
        self.received.append((data, address))


class PolicyTest(unittest.TestCase):
    def test_reject_invalid_policy(self):
        with self.assertRaises(ValueError):
            NatPolicy(mapping='invented')
        with self.assertRaises(ValueError):
            NatPolicy(filtering='invented')
        with self.assertRaises(ValueError):
            NatNetwork(loss=1)

    def test_mapping_independent_reuses_endpoint_symmetric_does_not(self):
        source = ('10.71.0.2', 1234)
        remote = [('192.0.2.1', 3478), ('203.0.113.20', 5000)]
        for policy, reuse in ((NatPolicy(), True), (NatPolicy(mapping='address-port-dependent'), False)):
            router = NatNetwork(policies=(policy, policy)).routers[0][-1]
            self.assertEqual(router.outbound(source, remote[0]) == router.outbound(source, remote[1]), reuse)

    def test_filtering_address_is_distinct_from_address_and_port(self):
        source, destination = ('10.71.0.2', 1234), ('203.0.113.20', 5000)
        for mode, same_ip_new_port, unknown_ip in (
            ('endpoint-independent', True, True),
            ('address-dependent', True, False),
            ('address-port-dependent', False, False),
        ):
            policy = NatPolicy(filtering=mode)
            network = NatNetwork(policies=(policy, policy))
            router = network.routers[0][-1]
            mapping = network.mappings[router.outbound(source, destination)]
            self.assertTrue(router.permits(mapping, destination))
            self.assertEqual(router.permits(mapping, (destination[0], 5001)), same_ip_new_port)
            self.assertEqual(router.permits(mapping, ('198.51.100.77', 5000)), unknown_ip)


class RoutingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.endpoints = []

    async def asyncTearDown(self):
        for endpoint in self.endpoints:
            endpoint.close()
        await asyncio.sleep(0)

    def peers(self, **kwargs):
        network = NatNetwork(latency_ms=0, **kwargs)
        protocols = [Sink(), Sink()]
        endpoints = [network.endpoint(side, asyncio.get_running_loop(), protocol)
                     for side, protocol in enumerate(protocols)]
        self.endpoints.extend(endpoints)
        return network, protocols, endpoints

    async def gather(self, protocols, endpoints):
        for endpoint in endpoints:
            request = stun.Message(message_method=stun.Method.BINDING, message_class=stun.Class.REQUEST)
            endpoint.sendto(bytes(request), STUN_ADDRESS)
        await asyncio.sleep(.03)
        addresses = [stun.parse_message(protocol.received.pop()[0]).attributes['XOR-MAPPED-ADDRESS']
                     for protocol in protocols]
        self.assertEqual([address[0] for address in addresses], list(PUBLIC_IPS))
        return addresses

    async def test_private_candidate_cannot_bypass_nat(self):
        network, protocols, endpoints = self.peers()
        endpoints[0].sendto(b'LAN shortcut', endpoints[1].address)
        await asyncio.sleep(.03)
        self.assertFalse(protocols[1].received)
        self.assertEqual(network.counts['unroutable_destination'], 1)
        self.assertEqual(network.counts['peer_delivered'], 0)

    async def test_nested_nat_drops_unsolicited_then_allows_hole_punch(self):
        network, protocols, endpoints = self.peers()
        addresses = await self.gather(protocols, endpoints)
        endpoints[0].sendto(b'not yet', addresses[1])
        await asyncio.sleep(.03)
        self.assertFalse(protocols[1].received)
        self.assertEqual(network.counts['nat_filter_dropped'], 1)
        endpoints[1].sendto(b'punch B', addresses[0])
        await asyncio.sleep(.03)
        endpoints[0].sendto(b'punch A', addresses[1])
        await asyncio.sleep(.03)
        self.assertEqual(protocols[0].received, [(b'punch B', addresses[1])])
        self.assertEqual(protocols[1].received, [(b'punch A', addresses[0])])
        self.assertEqual(network.snapshot()['mapping_counts'], [[1, 1], [1, 1]])
        self.assertEqual(network.counts['nat_inbound_translations'], 8)

    async def test_both_symmetric_do_not_accept_advertised_stun_endpoint(self):
        policy = NatPolicy(mapping='address-port-dependent')
        network, protocols, endpoints = self.peers(policies=(policy, policy))
        addresses = await self.gather(protocols, endpoints)
        for side in (0, 1):
            endpoints[side].sendto(b'peer probe', addresses[1 - side])
        await asyncio.sleep(.03)
        self.assertFalse(any(protocol.received for protocol in protocols))
        self.assertEqual(network.counts['nat_filter_dropped'], 2)
        self.assertEqual(network.snapshot()['mapping_counts'], [[2, 2], [2, 2]])

    async def test_stun_success_is_not_peer_connectivity(self):
        network, protocols, endpoints = self.peers(block_peer_udp=True)
        addresses = await self.gather(protocols, endpoints)
        for side in (0, 1):
            endpoints[side].sendto(b'peer probe', addresses[1 - side])
        await asyncio.sleep(.03)
        self.assertFalse(any(protocol.received for protocol in protocols))
        self.assertEqual(network.counts['stun_delivered'], 2)
        self.assertEqual(network.counts['peer_udp_blocked'], 2)

    async def test_closed_peer_does_not_receive_in_flight_packet(self):
        policy = NatPolicy(filtering='endpoint-independent')
        network, protocols, endpoints = self.peers(policies=(policy, policy))
        addresses = await self.gather(protocols, endpoints)
        endpoints[0].sendto(b'in flight', addresses[1])
        endpoints[1].close()
        await asyncio.sleep(.03)
        self.assertFalse(protocols[1].received)


if __name__ == '__main__':
    unittest.main()
