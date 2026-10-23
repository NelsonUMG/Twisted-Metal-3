import ctypes as C
import struct
import threading
import time
import unittest

from system256_peer_cable import PeerCable


def mailbox(command=2, call=0x80047EA0, send=b'LEFT', expected=4):
    ram = C.create_string_buffer(1024 * 1024)
    address = C.addressof(ram)
    struct.pack_into('<I4H5I', ram, 0x47900, 0x4F334D54, 6, 1,
                     command, 0, 0, len(send), expected, 0, call)
    if command == 2:
        struct.pack_into('<II', ram, 0x47920, 0x80010000, 0x80011000)
    C.memmove(address + 0x10000, send, len(send))
    return ram, address


def batch_mailbox(parts, recv_sizes, call=0x8003AA98):
    ram = C.create_string_buffer(1024 * 1024)
    address = C.addressof(ram)
    send_n, recv_n = sum(map(len, parts)), sum(recv_sizes)
    struct.pack_into('<I4H5I', ram, 0x47900, 0x4F334D54, 6, 1,
                     3, 0, 0, send_n, recv_n, 0, call)
    struct.pack_into('<II', ram, 0x47928, len(parts), len(recv_sizes))
    position = 0
    for index, part in enumerate(parts):
        offset = 0x10000 + index * 0x100
        struct.pack_into('<II', ram, 0x47930 + index * 8, 0x80000000 + offset, len(part))
        C.memmove(address + offset, part, len(part))
        position += len(part)
    for index, length in enumerate(recv_sizes):
        offset = 0x11000 + index * 0x100
        struct.pack_into('<II', ram, 0x47950 + index * 8, 0x80000000 + offset, length)
    return ram, address


class PeerCableTests(unittest.TestCase):
    def test_role_wait_has_no_deadline_while_transport_is_alive(self):
        cable = PeerCable(0, 99, lambda packet: None)
        ram, address = mailbox(command=1, send=b'', expected=0)
        cable.exchange(0, address, 256 * 1024 * 1024)
        header, _started = cable.role_pending
        cable.role_pending = (header, time.monotonic() - 3600)
        cable.check_role_timeout()
        self.assertFalse(cable.stopped)
        self.assertEqual(struct.unpack_from('<H', ram, 0x47906)[0], 1)

    def test_disconnect_still_fails_an_indefinite_role_wait(self):
        cable = PeerCable(0, 99, lambda packet: None)
        ram, address = mailbox(command=1, send=b'', expected=0)
        cable.exchange(0, address, 256 * 1024 * 1024)
        cable.stop('peer disconnected')
        self.assertTrue(cable.stopped)
        self.assertEqual(struct.unpack_from('<H', ram, 0x47906)[0], 4)
        self.assertEqual(cable.role_events[-1]['event'], 'role_cancelled')

    def test_connected_session_role_queries_do_not_require_peer_menu_lockstep(self):
        cables = self.pair()
        allocations = []
        for side in (0, 1, 0, 0, 1, 0, 1, 1):
            ram, address = mailbox(command=1, send=b'', expected=0)
            allocations.append(ram)
            cables[side].exchange(side, address, 256 * 1024 * 1024)
        self.assertEqual(struct.unpack_from('<H', allocations[-1], 0x47906)[0], 3)
        self.assertEqual([c.role_round for c in cables], [1, 1])

    def test_new_main_menu_cycle_negotiates_fresh_roles_with_monotonic_rounds(self):
        cables = self.pair()
        allocations = []
        for side in (0, 1):
            ram, address = mailbox(command=1, send=b'', expected=0)
            allocations.append(ram)
            cables[side].exchange(side, address, 256 * 1024 * 1024)
        self.assertTrue(all(c.role_agreed for c in cables))
        self.assertTrue(all(c.reset_role_cycle() for c in cables))
        second = []
        for side in (1, 0):
            ram, address = mailbox(command=1, send=b'', expected=0)
            second.append(ram)
            cables[side].exchange(side, address, 256 * 1024 * 1024)
        self.assertTrue(all(c.role_agreed for c in cables))
        self.assertEqual([c.role_round for c in cables], [2, 2])
        self.assertEqual([c.remote_role_round for c in cables], [2, 2])
        self.assertTrue(all(any(e['event'] == 'role_cycle_reset' for e in c.role_events)
                            for c in cables))

    def test_next_role_round_survives_asymmetric_main_menu_detection(self):
        cables = self.pair()
        allocations = []
        for side in (0, 1):
            ram, address = mailbox(command=1, send=b'', expected=0)
            allocations.append(ram)
            cables[side].exchange(side, address, 256 * 1024 * 1024)
        self.assertTrue(cables[0].reset_role_cycle())
        early, early_address = mailbox(command=1, send=b'', expected=0)
        cables[0].exchange(0, early_address, 256 * 1024 * 1024)
        self.assertFalse(cables[0].role_agreed)
        self.assertTrue(cables[1].role_agreed)  # still finishing the old menu flow
        self.assertTrue(cables[1].reset_role_cycle())
        late, late_address = mailbox(command=1, send=b'', expected=0)
        cables[1].exchange(1, late_address, 256 * 1024 * 1024)
        self.assertTrue(all(c.role_agreed for c in cables))
        self.assertEqual(struct.unpack_from('<H', early, 0x47906)[0], 3)
        self.assertEqual([c.role_round for c in cables], [2, 2])

    def pair(self):
        sides = [None, None]
        sides[0] = PeerCable(0, 99, lambda packet: sides[1].receive(packet), timeout=1)
        sides[1] = PeerCable(1, 99, lambda packet: sides[0].receive(packet), timeout=1)
        return sides

    def test_role_waits_for_peer_without_blocking_emulation(self):
        cables = self.pair()
        ram, address = mailbox(command=1, send=b'', expected=0)
        cables[0].exchange(0, address, 256 * 1024 * 1024)
        self.assertEqual(struct.unpack_from('<H', ram, 0x47906)[0], 1)
        peer_ram, peer_address = mailbox(command=1, send=b'', expected=0)
        cables[1].exchange(1, peer_address, 256 * 1024 * 1024)
        self.assertEqual(struct.unpack_from('<H', ram, 0x4790A)[0], 0x702)
        self.assertEqual(struct.unpack_from('<H', ram, 0x47906)[0], 3)

    def test_symmetric_transfer_crosses_peer_transport_and_finishes_both_sides(self):
        cables = self.pair()
        ram0, address0 = mailbox(send=b'HOST', expected=5)
        ram1, address1 = mailbox(send=b'GUEST', expected=4)
        threads = [threading.Thread(target=lambda: cables[0].exchange(0, address0, 256 * 1024 * 1024)),
                   threading.Thread(target=lambda: cables[1].exchange(1, address1, 256 * 1024 * 1024))]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(cables[0].error, None)
        self.assertEqual(cables[1].error, None)
        self.assertEqual(C.string_at(address0 + 0x11000, 5), b'GUEST')
        self.assertEqual(C.string_at(address1 + 0x11000, 4), b'HOST')
        self.assertEqual(struct.unpack_from('<H', ram0, 0x47906)[0], 3)
        self.assertEqual(struct.unpack_from('<H', ram1, 0x47906)[0], 3)

    def test_stale_epoch_and_wrong_side_are_rejected(self):
        cables = self.pair()
        packet = struct.pack('!4sQBBHIIIII', b'T3C1', 98, 1, 1, 2, 1, 1,
                             0x80047EA0, 0, 0)
        cables[0].receive(packet)
        self.assertTrue(cables[0].stopped)
        self.assertIn('Invalid P2P cable envelope', cables[0].error)

    def test_invalid_receive_pointer_fails_closed(self):
        cables = self.pair()
        ram, address = mailbox()
        struct.pack_into('<I', ram, 0x47924, 0xBF801000)
        cables[0].exchange(0, address, 256 * 1024 * 1024)
        self.assertTrue(cables[0].stopped)
        self.assertIn('Invalid cable RAM address', cables[0].error)
        self.assertEqual(struct.unpack_from('<H', ram, 0x47906)[0], 4)

    def test_gameplay_batch_scatter_gather_preserves_segment_order(self):
        cables = self.pair()
        sync_tail = struct.pack('<II', 30, 0x12345678)
        host_parts = [b'HEAD', bytes(range(24)), b'HS1!', sync_tail]
        guest_parts = [b'GHDR', bytes(reversed(range(24))), b'GS1!', sync_tail]
        sizes = [4, 24, 4, 8]
        host_ram, host_address = batch_mailbox(host_parts, sizes)
        guest_ram, guest_address = batch_mailbox(guest_parts, sizes)
        threads = [threading.Thread(target=lambda: cables[0].exchange(0, host_address, 256 * 1024 * 1024)),
                   threading.Thread(target=lambda: cables[1].exchange(1, guest_address, 256 * 1024 * 1024))]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        host_received = b''.join(C.string_at(host_address + 0x11000 + i * 0x100, size)
                                 for i, size in enumerate(sizes))
        guest_received = b''.join(C.string_at(guest_address + 0x11000 + i * 0x100, size)
                                  for i, size in enumerate(sizes))
        self.assertEqual(host_received, b''.join(guest_parts))
        self.assertEqual(guest_received, b''.join(host_parts))
        self.assertEqual(cables[0].gameplay, 1)
        self.assertEqual(cables[1].gameplay, 1)
        self.assertEqual(cables[0].time_mismatches, 0)
        self.assertEqual(cables[0].rng_mismatches, 0)
        self.assertEqual(struct.unpack_from('<H', host_ram, 0x47906)[0], 3)
        self.assertEqual(struct.unpack_from('<H', guest_ram, 0x47906)[0], 3)


if __name__ == '__main__':
    unittest.main()
