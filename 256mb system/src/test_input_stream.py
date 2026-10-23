import random
import struct
import unittest
from input_stream import InputStream,HEADER,ENTRY,WINDOW


class StreamTests(unittest.TestCase):
    def test_loss_reorder_ack_and_two_pads(self):
        a,b=InputStream(1,0),InputStream(1,1);randomizer=random.Random(44)
        pending=[]
        for frame in range(500):
            for stream in (a,b): stream.offer(frame,(frame<<16)|(frame^255))
            for source,dest in ((a,b),(b,a)):
                if randomizer.random()>.2: pending.append((dest,source.packet()))
            randomizer.shuffle(pending)
            for dest,data in pending: dest.receive(data)
            pending.clear()
            # Loss can defer consumption, never invent missing values.
            for stream in (a,b):
                while stream.consumed+1 in stream.incoming:
                    n=stream.consumed+1
                    self.assertEqual(stream.take(n),(n<<16)|(n^255))
        for _ in range(8): b.receive(a.packet());a.receive(b.packet())
        for stream in (a,b):
            while stream.consumed<499:
                n=stream.consumed+1;self.assertEqual(stream.take(n),(n<<16)|(n^255))
            self.assertLessEqual(len(stream.retired),128)
            self.assertLessEqual(len(stream.outgoing),WINDOW)

    def test_epoch_side_future_conflict_and_ack_guards(self):
        a,b=InputStream(42,0),InputStream(42,1)
        a.offer(0,0x80008000);self.assertTrue(b.receive(a.packet()))
        self.assertEqual(b.take(0),0x80008000)
        self.assertFalse(b.receive(HEADER.pack(b'T3I1',43,0,0xffffffff,0)))
        for packet in (HEADER.pack(b'T3I1',42,0,5,0),
                       HEADER.pack(b'T3I1',42,1,0xffffffff,0),
                       HEADER.pack(b'T3I1',42,0,0xffffffff,1)+ENTRY.pack(0,17),
                       HEADER.pack(b'T3I1',42,0,0xffffffff,1)+ENTRY.pack(999,17)):
            with self.assertRaises(ValueError): b.receive(packet)

    def test_missing_input_times_out_and_never_predicts(self):
        stream=InputStream(1,0)
        with self.assertRaises(TimeoutError): stream.take(0,timeout=.001)
        self.assertEqual(stream.consumed,-1)
        stream.close()
        with self.assertRaises(RuntimeError): stream.take(0)

    def test_backpressure_and_malformed_packets(self):
        stream=InputStream(1,0)
        for i in range(WINDOW):stream.offer(i,0)
        with self.assertRaises(BufferError):stream.offer(WINDOW,0)
        for packet in (b'',b'a'*HEADER.size,stream.packet()+b'x'):
            with self.assertRaises(ValueError):stream.receive(packet)


if __name__=='__main__':unittest.main()
