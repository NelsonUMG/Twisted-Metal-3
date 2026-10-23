import ctypes as C
import struct
import threading
import unittest
from twin_core import LocalCable


class CableTests(unittest.TestCase):
    def memory(self,command=2,call=0x80047ea0,send=b'ABCD',expected=4):
        # The adapter is given the full validated region size, but this fixture
        # intentionally allocates only the low ranges actually touched.
        ram=C.create_string_buffer(1024*1024)
        address=C.addressof(ram)
        struct.pack_into('<I4H5I',ram,0x47900,0x4f334d54,6,1,command,0,0,len(send),expected,0,call)
        struct.pack_into('<II',ram,0x47920,0x80010000,0x80011000)
        C.memmove(address+0x10000,send,len(send))
        return ram,address

    def test_transfer_is_exact_and_unmatched_wait_has_no_fake_data(self):
        cable=LocalCable();a,pa=self.memory(send=b'LEFT');b,pb=self.memory(send=b'RITE')
        thread=threading.Thread(target=cable.exchange,args=(0,pa,256*1024*1024));thread.start()
        self.assertTrue(thread.is_alive())
        cable.exchange(1,pb,256*1024*1024);thread.join(1)
        self.assertFalse(thread.is_alive());self.assertIsNone(cable.error)
        self.assertEqual(C.string_at(pa+0x11000,4),b'RITE')
        self.assertEqual(C.string_at(pb+0x11000,4),b'LEFT')
        self.assertEqual(struct.unpack_from('<H',a,0x47906)[0],3)

    def test_mismatched_call_fails_both_consoles(self):
        cable=LocalCable();a,pa=self.memory();b,pb=self.memory(call=0x80047eb8)
        t=threading.Thread(target=cable.exchange,args=(0,pa,256*1024*1024));t.start()
        cable.exchange(1,pb,256*1024*1024);t.join(1)
        self.assertTrue(cable.stopped);self.assertIsNotNone(cable.error)
        self.assertEqual(struct.unpack_from('<H',a,0x47906)[0],4)
        self.assertEqual(struct.unpack_from('<H',b,0x47906)[0],4)

    def test_role_and_invalid_pointer(self):
        cable=LocalCable();ram,p=self.memory(command=1)
        cable.exchange(0,p,256*1024*1024)
        self.assertEqual(struct.unpack_from('<H',ram,0x4790a)[0],0x702)
        ram,p=self.memory();struct.pack_into('<I',ram,0x47920,0xbf801000)
        cable.exchange(0,p,256*1024*1024)
        self.assertTrue(cable.stopped);self.assertIsNotNone(cable.error)


if __name__=='__main__':unittest.main()
