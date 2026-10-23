import time
import unittest
from collections import OrderedDict, deque
from system256_bridge import (CABLE_FRAGMENT_HEADER, CABLE_FRAGMENT_MAGIC,
                              CABLE_FRAGMENT_MAX, System256Peer)


class BridgeEnvelopeTests(unittest.TestCase):
    def peer(self):
        peer = System256Peer.__new__(System256Peer)
        peer.engine_bridge = None
        peer.engine_pending = deque(maxlen=128)
        peer.engine_generation = 7
        peer.cable_receive_sequence = 0
        peer.cable_fragments = OrderedDict()
        peer.last_received = 0
        peer.failures = []
        peer.fail = peer.failures.append
        return peer

    def test_separate_reliable_engine_envelope(self):
        peer = self.peer()
        peer._control_message(b'S256{"loaded":true}')
        self.assertEqual(list(peer.engine_pending), [b'M{"loaded":true}'])
        self.assertGreater(peer.last_received, 0)

    def test_input_envelope_does_not_enter_legacy_cable_bridge(self):
        peer = self.peer()
        peer._data_message(b'T3I1test')
        self.assertEqual(list(peer.engine_pending), [b'DT3I1test'])

    def test_preparation_queue_is_bounded(self):
        peer = self.peer()
        for _ in range(129): peer.deliver_engine(b'Dx')
        self.assertEqual(len(peer.engine_pending), 128)
        self.assertEqual(len(peer.failures), 1)

    def test_reliable_cable_fragments_are_reassembled_before_engine_delivery(self):
        peer = self.peer()
        payload = bytes((i % 251 for i in range(CABLE_FRAGMENT_MAX * 2 + 37)))
        count = (len(payload) + CABLE_FRAGMENT_MAX - 1) // CABLE_FRAGMENT_MAX
        for index in reversed(range(count)):
            fragment = payload[index*CABLE_FRAGMENT_MAX:(index+1)*CABLE_FRAGMENT_MAX]
            peer._control_message(CABLE_FRAGMENT_HEADER.pack(
                CABLE_FRAGMENT_MAGIC, 7, 1, index, count, len(payload)) + fragment)
        self.assertEqual(list(peer.engine_pending), [b'C' + payload])
        self.assertEqual(peer.cable_receive_sequence, 1)
        self.assertFalse(peer.failures)

    def test_wrong_generation_cable_packet_fails_closed(self):
        peer = self.peer()
        payload = b'one byte'
        peer._control_message(CABLE_FRAGMENT_HEADER.pack(
            CABLE_FRAGMENT_MAGIC, 6, 1, 0, 1, len(payload)) + payload)
        self.assertEqual(len(peer.failures), 1)
        self.assertIn('inválidos', peer.failures[0])


if __name__ == '__main__': unittest.main()
