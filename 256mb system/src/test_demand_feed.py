import unittest
from demand_feed import DemandFeed
from input_stream import InputStream


class Peer:
    def __init__(self):self.sent=0
    def send_inputs(self):self.sent+=1


class DemandTests(unittest.TestCase):
    def test_live_sampler_delay_and_two_controller_masks(self):
        a,b=InputStream(1,0),InputStream(1,1)
        # Calls represent input sampled NOW, applied 3 emulated frames later.
        pads=[0x12348000,0x80000001,0x00008000,0x01230002,0x80008000]
        feed=DemandFeed(a,Peer(),0,3,lambda frame:pads[frame-3])
        try:
            values=[]
            for frame in range(5):
                lo,hi=feed(0,frame);values.append(lo|(hi<<16))
                b.receive(a.packet())
                self.assertEqual(b.take(frame),values[-1])
            self.assertEqual(values,[0,0,0]+pads[:2])
            self.assertLessEqual(len(feed.local),3)
        finally:feed.close()

    def test_remote_input_never_substitutes_local_controller(self):
        a,b=InputStream(1,0),InputStream(1,1)
        feed=DemandFeed(a,Peer(),0,3,lambda frame:0xaaaaaaaa)
        try:
            b.offer(0,0x12345678);a.receive(b.packet())
            self.assertEqual(feed(1,0),(0x5678,0x1234))
        finally:feed.close()

    def test_new_local_input_is_sent_without_waiting_for_retry_timer(self):
        stream=InputStream(1,0);peer=Peer()
        feed=DemandFeed(stream,peer,0,2,lambda frame:0x80001234)
        try:
            before=peer.sent
            feed(0,0)
            self.assertGreater(peer.sent,before)
            self.assertEqual(stream.outgoing[2],0x80001234)
        finally:feed.close()


if __name__=='__main__':unittest.main()
