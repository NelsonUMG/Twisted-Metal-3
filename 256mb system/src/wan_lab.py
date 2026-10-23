"""Public Cloudflare signaling + real encrypted ICE + real TM3 twin-core.

Only ICE UDP is simulated. CF is a real directory, not a packet delay relay.
The owned test pre-records menu navigation; it is NOT a shipped lobby mode.
"""
import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
import queue
import secrets
import sys
import threading
import time

BASE=Path(__file__).resolve().parent.parent
ROOT=BASE.parent
sys.path[:0]=[str(ROOT/'network'),str(ROOT/'tools')]
from worker_directory import WorkerDirectory
from ice_nat_lab import SimulatedP2PSession,NatNetwork,isolated_ice_addresses
from input_stream import InputStream
from capture_reference import run_reference

PUBLIC='https://tm3-room-directory.tm3-room-directory.workers.dev'


class FramePeer(SimulatedP2PSession):
    def __init__(self,network,side,stream):
        self.stream=stream
        super().__init__(network,side)

    def _data_message(self,data):
        try:
            self.stream.receive(data)
            self.last_received=time.monotonic();self.received+=1
        except ValueError as exc:
            self.stream.close(str(exc));self.fail('Invalid SYSTEM256 input stream')

    def send_inputs(self):
        packet=self.stream.packet()
        def send():
            if self.data.readyState=='open' and self.data.bufferedAmount<8192:
                self.data.send(packet);self.sent+=1
        self.loop.call_soon_threadsafe(send)


class Feed:
    """Inject only confirmed remote controller frames into the real core."""
    def __init__(self,recording,peers,streams,buffer_frames,local_side):
        self.recording,self.peers,self.streams=recording,peers,streams
        self.buffer_frames,self.local_side=buffer_frames,local_side
        self.offsets=None;self.local={};self.condition=threading.Condition()
        self.stop=threading.Event();self.thread=None;self.started=None;self.stalls=[]
        self.ready=threading.Event()
        self.consumed=[0,0];self.error=None

    def begin(self,offsets):
        self.offsets=offsets
        self.thread=threading.Thread(target=self.publish,daemon=True);self.thread.start()
        if not self.ready.wait(2):raise TimeoutError('Input publisher did not start')

    def publish(self):
        try:
            self.started=time.perf_counter();self.ready.set();frame=0
            while not self.stop.is_set():
                for side,stream in enumerate(self.streams):
                    index=self.offsets[side]+frame
                    value=self.recording[side][index] if index<len(self.recording[side]) else 0
                    stream.offer(frame,value)
                    if side==self.local_side:
                        with self.condition: self.local[frame]=value;self.condition.notify_all()
                for peer in self.peers: peer.send_inputs()
                # The unused replica's receipt queue still needs a consumer.
                other=self.streams[1-self.local_side]
                with other.condition:
                    while other.consumed+1 in other.incoming: other.take(other.consumed+1)
                frame+=1
                self.stop.wait(max(0,self.started+frame/59.94-time.perf_counter()))
        except BaseException as exc:
            self.error=repr(exc)
            for stream in self.streams:stream.close(self.error)
            with self.condition:self.condition.notify_all()

    def __call__(self,side,frame):
        if self.offsets is None or frame<self.offsets[side]:
            value=self.recording[side][frame]
        else:
            n=frame-self.offsets[side]
            deadline=self.started+(n+self.buffer_frames)/59.94
            wait=deadline-time.perf_counter()
            if wait>0:self.stop.wait(wait)
            start=time.perf_counter()
            if side==self.local_side:
                with self.condition:
                    while n not in self.local:
                        if self.error:raise RuntimeError(self.error)
                        if time.perf_counter()-start>5:raise TimeoutError('Local input publisher')
                        self.condition.wait(.05)
                    value=self.local.pop(n)
            else:value=self.streams[self.local_side].take(n)
            extra=(time.perf_counter()-max(start,deadline))*1000
            if extra>2:self.stalls.append(dict(side=side,frame=n,extra_wait_ms=extra))
            self.consumed[side]+=1
        return value & 65535,value>>16

    def close(self):
        self.stop.set()
        for stream in self.streams:stream.close()
        with self.condition:self.condition.notify_all()
        if self.thread:self.thread.join(3)


def manifest():
    def sha(path):
        with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()
    return dict(protocol='TM3-SYSTEM256-INPUT1',core_sha256=sha(BASE/'core_source/mednafen_psx_libretro.dll'),
                scus_sha256=sha(BASE/'game/SCUS_942.49.system256'),cpu_budget=175,ram_bytes=268435456,
                consoles_per_pc=2,pads_per_console=2,rollback=False,frame_clock='59.94')


def require_capabilities(message,capability,epoch,remote_owner):
    expected=dict(kind='system256_ready',system256=capability,epoch=str(epoch),owner=remote_owner)
    if message!=expected:raise ValueError('Incompatible SYSTEM256 core/content/settings/session')


def run(rtt,jitter,loss,local_side,seed):
    expected=json.loads((BASE/'reports/reference.json').read_text())
    network=NatNetwork(latency_ms=rtt/2,jitter_ms=jitter,loss=loss,seed=seed)
    epoch=secrets.randbits(64) or 1
    streams=[InputStream(epoch,side) for side in (0,1)]
    peers=[];clients=[];tokens=[];feed=None
    def rpc(side,op,**kwargs):
        time.sleep(.16)
        return clients[side].request(dict(op=op,token=tokens[side],**kwargs))
    try:
        with isolated_ice_addresses():
            for side in (0,1):
                client=WorkerDirectory(PUBLIC);clients.append(client)
                tokens.append(client.request(dict(op='login',name=f'QA SYSTEM256 {side} '+secrets.token_hex(3),automatic_ice=1))['token'])
                peers.append(FramePeer(network,side,streams[side]))
            rid=rpc(0,'create',description=f'QA 256 experimental RTT {rtt}')['room']['id']
            assert any(r['id']==rid for r in rpc(1,'poll')['rooms'])
            rpc(1,'join',room=rid);generation=rpc(0,'start')['room']['generation']
            rpc(0,'ice_offer',generation=generation,code=peers[0].create_offer())
            offer=rpc(1,'poll')['room']['transport']['offer']
            rpc(1,'ice_answer',generation=generation,code=peers[1].create_answer(offer))
            peers[0].accept_answer(rpc(0,'poll')['room']['transport']['answer'])
            assert all(peer.connected.wait(30) for peer in peers),[p.error for p in peers]
            rpc(0,'ice_ready',generation=generation);rpc(1,'ice_ready',generation=generation)
            capability=manifest()
            for peer in peers:peer.send_message(dict(system256=capability,epoch=str(epoch)))
            for peer in peers:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    try:kind,value=peer.events.get(timeout=.1)
                    except queue.Empty:continue
                    if kind=='message':
                        assert value==dict(system256=capability,epoch=str(epoch));break
                else:raise AssertionError('SYSTEM256 capability handshake missing')
            # One-way delay + jitter + 100 ms resend margin; no promise under
            # arbitrary outages. 400 ms RTT does not imply 400 ms each way.
            buffer_frames=math.ceil((rtt/2+jitter+100)/1000*59.94)
            feed=Feed(expected['input_recording'],peers,streams,buffer_frames,local_side)
            result=run_reference(600,replay=expected['input_recording'],feed=feed,label=f'wan_{rtt}')
            feed.close()
            result.pop('input_recording')
            result.update(real_cloudflare_directory=True,automatic_signaling=True,manual_codes=False,
                simulated_game_network=True,simulated_rtt_ms=rtt,one_way_delay_ms=rtt/2,
                jitter_each_way_ms=jitter,random_udp_loss=loss,seed=seed,
                input_buffer_frames=buffer_frames,input_buffer_ms=buffer_frames/59.94*1000,
                local_console=local_side,peer_rtt=[p.latency_snapshot() for p in peers],
                network=network.snapshot(),input_stalls=feed.stalls,input_publisher_error=feed.error,
                input_consumed=feed.consumed,
                wire_bytes=[s.sent_bytes for s in streams],packets=[s.sent_packets for s in streams],
                checkpoints_equal_reference=result['checkpoints']==expected['checkpoints'],
                pre_recorded_menu_prefix=True,interactive_lobby_ready=False,
                audio_verified=False,controller_2_active_gameplay_verified=False,
                manifest=capability)
            windows=result['windows'][2:] # exclude buffer startup and warmup
            result['steady_time_units_per_second']=sum(30 for w in windows)/sum(w['seconds'] for w in windows)
            passed=(result['checkpoints_equal_reference'] and not feed.error and not result['time_mismatches']
                    and not result['rng_mismatches'] and result['steady_time_units_per_second']>=29)
            result['target_29_passed']=passed
            (BASE/f'reports/wan_{rtt}.json').write_text(json.dumps(result,indent=2))
            print(json.dumps({k:result[k] for k in ('simulated_rtt_ms','steady_time_units_per_second',
                'target_29_passed','checkpoints_equal_reference','input_buffer_ms','input_consumed','wire_bytes','peer_rtt')},indent=2),flush=True)
            return passed
    finally:
        if feed:feed.close()
        for peer in peers:peer.close()
        for side,client in enumerate(clients):
            try:
                if side<len(tokens):rpc(side,'logout')
            except Exception:pass
            client.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rtt',type=int,choices=(0,250,400),default=250)
    p.add_argument('--jitter',type=float,default=10)
    p.add_argument('--loss',type=float,default=.01)
    p.add_argument('--local-side',type=int,choices=(0,1),default=0)
    p.add_argument('--seed',type=int,default=25622)
    a=p.parse_args()
    raise SystemExit(0 if run(a.rtt,a.jitter,a.loss,a.local_side,a.seed) else 1)
