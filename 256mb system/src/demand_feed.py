"""Live adapter: each owner produces future controller frames on demand.

The sampler can be real keyboard/gamepad input. Tests provide recorded pads.
No prerecorded prefix, clock resets, worldstate or cable data go over WAN.
"""
import threading
import time


class DemandFeed:
    def __init__(self,stream,peer,side,delay,sampler,initial=None):
        if not 1<=delay<=120:raise ValueError('Input delay outside supported range')
        self.stream,self.peer,self.side,self.delay,self.sampler=stream,peer,side,delay,sampler
        self.local={};self.stop=threading.Event();self.error=None;self.consumed=[0,0]
        self.waits=[]
        for frame in range(delay):
            value=initial[frame] if initial else 0
            self.local[frame]=value;stream.offer(frame,value)
        self.thread=threading.Thread(target=self.resend,daemon=True);self.thread.start()

    def resend(self):
        try:
            while not self.stop.is_set():
                self.peer.send_inputs();self.stop.wait(1/60)
        except BaseException as exc:
            self.error=repr(exc);self.stream.close(self.error)

    def __call__(self,side,frame):
        if side==self.side:
            future=frame+self.delay
            value=self.sampler(future)
            self.stream.offer(future,value);self.local[future]=value
            # First transmission must not wait for the periodic retry timer.
            # Keep that timer independent for loss recovery while cores wait.
            self.peer.send_inputs()
            value=self.local.pop(frame)
        else:
            start=time.perf_counter();value=self.stream.take(frame,timeout=10)
            wait=(time.perf_counter()-start)*1000
            if wait>2:self.waits.append(dict(frame=frame,wait_ms=wait))
        self.consumed[side]+=1
        return value&65535,value>>16

    def close(self):
        self.stop.set();self.stream.close()
        self.thread.join(3)
