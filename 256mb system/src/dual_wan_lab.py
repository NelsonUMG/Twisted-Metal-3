"""Four real cores: two complete local pairs exchanging only future inputs.

Real public Worker and DTLS/SCTP. Controlled dual-CGNAT UDP simulator.
All controller frames, INCLUDING BOOT/MENUS, use the same demand pipeline.
"""
import argparse
import ctypes as C
import hashlib
import json
import math
import os
import queue
from pathlib import Path
import secrets
import tempfile
import threading
import time
from wan_lab import BASE,PUBLIC,WorkerDirectory,NatNetwork,FramePeer,isolated_ice_addresses,manifest,require_capabilities
from input_stream import InputStream
from demand_feed import DemandFeed
from twin_core import Core,LocalCable


def run(rtt=400,seed=25624,interactive=False,input_delay_frames=None):
    if input_delay_frames is not None and not 1<=input_delay_frames<=120:
        raise ValueError('Input delay must be between 1 and 120 frames')
    expected=json.loads((BASE/'reports/reference.json').read_text())
    network=NatNetwork(latency_ms=rtt/2,jitter_ms=10,loss=.01,seed=seed)
    epoch=secrets.randbits(64) or 1
    streams=[InputStream(epoch,side) for side in (0,1)]
    peers=[];clients=[];tokens=[];feeds=[];cores=[[],[]];threads=[];errors=[]
    cables=[LocalCable(),LocalCable()];checks=[[],[]];windows=[[],[]];last=[None,None]
    frame_samples=[[],[]]
    ui=None
    if interactive:
        from manual_windows import ManualWindows
        ui=ManualWindows(BASE,rtt)
    def rpc(side,op,**kwargs):
        time.sleep(.16);return clients[side].request(dict(op=op,token=tokens[side],**kwargs))
    os.environ.update(TM3O_STANDARD_PS1='0',TM3O_DIAGNOSTICS='0')
    try:
        with isolated_ice_addresses(),tempfile.TemporaryDirectory(prefix='tm3_dual_wan_') as folder:
            try:
                for node in (0,1):
                    client=WorkerDirectory(PUBLIC);clients.append(client)
                    tokens.append(client.request(dict(op='login',name=f'QA twin full {node} '+secrets.token_hex(3),automatic_ice=1))['token'])
                    peers.append(FramePeer(network,node,streams[node]))
                rid=rpc(0,'create',description='QA experimental 256 - full twin replicas')['room']['id']
                assert any(r['id']==rid for r in rpc(1,'poll')['rooms'])
                rpc(1,'join',room=rid);generation=rpc(0,'start')['room']['generation']
                rpc(0,'ice_offer',generation=generation,code=peers[0].create_offer())
                offer=rpc(1,'poll')['room']['transport']['offer']
                rpc(1,'ice_answer',generation=generation,code=peers[1].create_answer(offer))
                peers[0].accept_answer(rpc(0,'poll')['room']['transport']['answer'])
                assert all(p.connected.wait(30) for p in peers),[p.error for p in peers]
                capability=manifest()
                for node,peer in enumerate(peers):
                    peer.send_message(dict(kind='system256_ready',system256=capability,epoch=str(epoch),owner=node))
                for node,peer in enumerate(peers):
                    deadline=time.monotonic()+6
                    while time.monotonic()<deadline:
                        try:kind,value=peer.events.get(timeout=.1)
                        except queue.Empty:continue
                        if kind=='message':
                            require_capabilities(value,capability,epoch,1-node);break
                    else:raise AssertionError('Encrypted capability handshake missing')
                delay=input_delay_frames if input_delay_frames is not None else math.ceil((rtt/2+10+100)/1000*59.94)
                for node in (0,1):
                    recording=expected['input_recording'][node]
                    sampler=(lambda frame,n=node:ui.sample(n,frame)) if interactive else (lambda frame,rec=recording:rec[frame] if frame<len(rec) else 0)
                    feeds.append(DemandFeed(streams[node],peers[node],node,delay,sampler,
                        initial=None if interactive else recording[:delay]))
                    for role in (0,1):
                        cores[node].append(Core(BASE/'core_source/mednafen_psx_libretro.dll',
                            BASE/'game/TM3_SYSTEM256.cue',Path(folder)/str(node)/str(role),role,cables[node],feeds[node]))
                        if interactive:cores[node][-1].capture_every=1 if role==node else 0
                # No core or RAM is shared: four distinct DLLs and RAM allocations.
                assert len({core.ram for pair in cores for core in pair})==4
                def observe(node,c):
                    if interactive:return
                    now=time.perf_counter();times=[core.word(0x895a8) for core in cores[node]]
                    if c.gameplay==30:last[node]=(now,times)
                    if last[node] and c.gameplay%30==0 and c.gameplay>30:
                        dt=now-last[node][0];deltas=[(a-b)&0xffffffff for a,b in zip(times,last[node][1])]
                        assert deltas==[30,30],deltas
                        windows[node].append(dict(tick=c.gameplay,seconds=dt,actual_time_deltas=deltas,time_units_per_s=deltas[0]/dt))
                        last[node]=(now,times)
                    if c.gameplay%100==0:
                        checkpoint=dict(tick=c.gameplay,consoles=[dict(frame=core.frame,time=core.word(0x895a8),
                            ram_sha256=hashlib.sha256(C.string_at(core.ram,16*1024*1024)).hexdigest()) for core in cores[node]])
                        checks[node].append(checkpoint)
                        print(f'node{node}',json.dumps(checkpoint),flush=True)
                    if c.gameplay>=600:c.stop()
                for node,cable in enumerate(cables):cable.observer=lambda c,n=node:observe(n,c)
                started=time.perf_counter();cpu_started=time.process_time()
                def execute(node,core):
                    try:
                        while not cables[node].stopped:
                            before=time.perf_counter();core.step()
                            if not interactive and cables[node].gameplay>30:frame_samples[node].append((time.perf_counter()-before)*1000)
                            wait=started+core.frame/59.94-time.perf_counter()
                            if wait>0:time.sleep(wait)
                    except BaseException as exc:
                        errors.append(dict(node=node,role=core.side,error=repr(exc)))
                        for c in cables:c.stop()
                threads=[threading.Thread(target=execute,args=(n,core),daemon=True) for n,pair in enumerate(cores) for core in pair]
                for t in threads:t.start()
                deadline=float('inf') if interactive else time.monotonic()+125
                while any(t.is_alive() for t in threads) and time.monotonic()<deadline:
                    if interactive:
                        ui.update(cores,cables,peers,feeds)
                        if ui.closed:break
                    time.sleep(.012 if interactive else .2)
                for cable in cables:cable.stop()
                if interactive:
                    for feed in feeds:feed.close()
                for t in threads:t.join(12)
                assert not any(t.is_alive() for t in threads),'Owned core thread did not stop'
                if interactive:return not errors
                elapsed=time.perf_counter()-started;cpu=time.process_time()-cpu_started
                for feed in feeds:feed.close()
                rates=[]
                for node in (0,1):
                    rows=windows[node][2:]
                    rates.append(sum(w['actual_time_deltas'][0] for w in rows)/sum(w['seconds'] for w in rows) if rows else 0)
                    for core in cores[node]:core.screenshot(BASE/f'reports/dual_{rtt}_node{node}_role{core.side}.bmp')
                result=dict(kind='four_real_cores_two_complete_replicas',real_cloudflare_directory=True,
                    manual_ice_codes=False,all_frames_use_input_pipeline=True,pre_recorded_local_menu_prefix=False,
                    sampler='recorded controller fixture, replaceable with live pads',actual_wan=False,
                    encrypted_capability_handshake=True,
                    simulated_rtt_ms=rtt,jitter_each_way_ms=10,random_udp_loss=.01,seed=seed,
                    virtual_console_ram_pointers_distinct=True,cpu_budget_percent=175,
                    input_delay_frames=delay,input_delay_ms=delay/59.94*1000,
                    elapsed_s=elapsed,process_cpu_seconds=cpu,
                    steady_actual_time_units_per_second=rates,windows=windows,checkpoints=checks,
                    per_role_full_16mib_ram_matches_reference=[row==expected['checkpoints'] for row in checks],
                    replicas_match_each_other=checks[0]==checks[1],
                    gameplay_ticks=[c.gameplay for c in cables],time_mismatches=[c.time_mismatches for c in cables],
                    rng_mismatches=[c.rng_mismatches for c in cables],cable_errors=[c.error for c in cables],errors=errors,
                    feed_errors=[f.error for f in feeds],input_waits=[f.waits for f in feeds],
                    frame_core_ms_mean=[sum(s)/len(s) if s else None for s in frame_samples],
                    frame_core_ms_max=[max(s) if s else None for s in frame_samples],
                    peer_rtt=[p.latency_snapshot() for p in peers],network=network.snapshot(),
                    wire_bytes=[s.sent_bytes for s in streams],manifest=manifest(),
                    complete_seven_maps=False,interactive_lobby_ready=False,audio_verified=False,
                    production_replaced=False)
                result['passed']=(all(row==expected['checkpoints'] for row in checks)
                    and all(rate>=29 for rate in rates) and not errors and not any(c.error for c in cables))
                suffix=f'_delay{delay}' if input_delay_frames is not None else ''
                (BASE/f'reports/dual_wan_{rtt}{suffix}.json').write_text(json.dumps(result,indent=2))
                print(json.dumps({k:result[k] for k in ('passed','steady_actual_time_units_per_second',
                    'replicas_match_each_other','input_delay_ms','elapsed_s','errors','cable_errors','wire_bytes')},indent=2),flush=True)
                return result['passed']
            finally:
                for cable in cables:cable.stop()
                for feed in feeds:feed.close()
                for t in threads:t.join(12)
                for pair in cores:
                    for core in pair:core.close()
    finally:
        if ui:ui.destroy()
        for peer in peers:peer.close()
        for side,client in enumerate(clients):
            try:
                if side<len(tokens):rpc(side,'logout')
            except Exception:pass
            client.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rtt',type=int,choices=(80,250,400),default=400)
    p.add_argument('--seed',type=int,default=25624)
    p.add_argument('--interactive',action='store_true')
    p.add_argument('--input-delay-frames',type=int,choices=range(1,121))
    a=p.parse_args();raise SystemExit(0 if run(a.rtt,a.seed,a.interactive,a.input_delay_frames) else 1)
