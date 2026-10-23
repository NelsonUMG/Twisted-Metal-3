"""Bounded confirmed-input protocol for two pads per PC, no world prediction.

Wire is carried inside DTLS/SCTP, never accepted from unauthenticated UDP.
Receiver ACKs contiguous INPUT receipt, not emulation or world consistency.
Frames cannot wrap: start another epoch before 2**32-1.
"""
from collections import OrderedDict
import struct
import threading
import time

HEADER=struct.Struct('!4sQBIB')  # magic, epoch, source console, ACK, entry count
ENTRY=struct.Struct('!II')
NO_ACK=0xffffffff
WINDOW=256
MAX_ENTRIES=24


class InputStream:
    def __init__(self, epoch, side):
        if not 0<epoch<2**64 or side not in (0,1): raise ValueError('Invalid input session')
        self.epoch,self.side=epoch,side
        self.outgoing=OrderedDict();self.incoming={};self.retired=OrderedDict()
        self.received_through=-1;self.acked=-1;self.sent_through=-1;self.consumed=-1
        self.condition=threading.Condition();self.error=None
        self.sent_packets=self.received_packets=self.sent_bytes=self.waits=0

    def offer(self, frame, pads):
        with self.condition:
            if frame!=self.sent_through+1 or not 0<=pads<2**32 or frame>=NO_ACK:
                raise ValueError('Input publication must be contiguous u32 frames')
            if len(self.outgoing)>=WINDOW: raise BufferError('Unacknowledged input window full')
            self.outgoing[frame]=pads;self.sent_through=frame

    def packet(self):
        with self.condition:
            entries=list(self.outgoing.items())
            # Oldest gaps and newest inputs both get a bounded opportunity.
            chosen=dict(entries[:12]+entries[-12:])
            payload=HEADER.pack(b'T3I1',self.epoch,self.side,
                self.received_through if self.received_through>=0 else NO_ACK,len(chosen))
            payload+=b''.join(ENTRY.pack(frame,value) for frame,value in sorted(chosen.items()))
            self.sent_packets+=1;self.sent_bytes+=len(payload)
            return payload

    def receive(self, packet):
        with self.condition:
            if not isinstance(packet,bytes) or len(packet)<HEADER.size: raise ValueError('Input header')
            magic,epoch,side,ack,count=HEADER.unpack_from(packet)
            if magic!=b'T3I1' or side!=1-self.side or count>MAX_ENTRIES or len(packet)!=HEADER.size+count*ENTRY.size:
                raise ValueError('Input framing')
            if epoch!=self.epoch: return False  # A retired generation cannot cross a restart.
            if ack!=NO_ACK and ack>self.sent_through: raise ValueError('ACK beyond published inputs')
            if ack!=NO_ACK and ack>self.acked:
                self.acked=ack
                while self.outgoing and next(iter(self.outgoing))<=ack: self.outgoing.popitem(last=False)
            entries=[ENTRY.unpack_from(packet,HEADER.size+i*ENTRY.size) for i in range(count)]
            if len({f for f,_ in entries})!=len(entries): raise ValueError('Duplicate packet frame')
            # Validate atomically before mutating the incoming stream.
            for frame,value in entries:
                if frame>=NO_ACK or frame>self.consumed+WINDOW: raise ValueError('Input exceeds bounded window')
                previous=self.incoming.get(frame,self.retired.get(frame))
                if previous is not None and previous!=value: raise ValueError('Conflicting confirmed input')
            for frame,value in entries:
                if frame>self.consumed: self.incoming[frame]=value
            while self.received_through+1 in self.incoming or self.received_through+1 in self.retired:
                self.received_through+=1
            self.received_packets+=1;self.condition.notify_all()
            return True

    def take(self, frame, timeout=5):
        with self.condition:
            if frame!=self.consumed+1: raise ValueError('Input consumption must be contiguous')
            deadline=time.monotonic()+timeout
            waited=False
            while frame not in self.incoming:
                if self.error: raise RuntimeError(self.error)
                if not waited: self.waits+=1;waited=True
                remaining=deadline-time.monotonic()
                if remaining<=0: raise TimeoutError(f'No confirmed input for frame {frame}')
                self.condition.wait(min(.1,remaining))
            value=self.incoming.pop(frame);self.consumed=frame;self.retired[frame]=value
            if len(self.retired)>128: self.retired.popitem(last=False)
            return value

    def close(self, error='Input stream closed'):
        with self.condition: self.error=error;self.condition.notify_all()
