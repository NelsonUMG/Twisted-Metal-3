"""Record actual TM3 controller inputs and per-role RAM at linked boundaries."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from twin_core import Core, LocalCable
from probe_twin import scripted

BASE = Path(__file__).resolve().parent.parent


def run_reference(ticks=600, replay=None, feed=None, paced=False, label='reference'):
    os.environ.update(TM3O_STANDARD_PS1='0', TM3O_DIAGNOSTICS='0')
    cable = LocalCable(); cores=[]; threads=[]; errors=[]
    entered=[(-1,0),(-1,0)]; recording=[[],[]]; checkpoints=[]; windows=[]
    benchmark_start=None; last_window=None
    def inputs(side, frame):
        if feed: result=feed(side, frame)
        elif replay is not None:
            assert frame < len(replay[side]), (side,frame,'recording exhausted')
            value=replay[side][frame]; result=(value & 65535, value >> 16)
        else:
            menu=cores[side].word(0x89a0c); previous,since=entered[side]
            if previous != menu: since=frame; entered[side]=(menu,since)
            age=frame-since
            if cable.gameplay>10:
                # Exercise acceleration, steering and weapons, not a frozen
                # neutral-input scene. These are ordinary controller masks.
                cycle=(cable.gameplay//45+side)%4
                result=(1 | ((1<<6) if cycle==1 else (1<<7) if cycle==2 else 0)
                        | ((1<<1) if cable.gameplay%40<4 else 0), 0)
            elif menu==0x8007ffe8:
                result=((1<<4 if 10<=age<20 else (1 if age%120 in range(40,55) else 0)),0)
            else: result=scripted(side,frame)
        recording[side].append(result[0] | (result[1]<<16))
        return result
    with tempfile.TemporaryDirectory(prefix='tm3_reference_') as folder:
        try:
            for side in (0,1):
                cores.append(Core(BASE/'core_source/mednafen_psx_libretro.dll', BASE/'game/TM3_SYSTEM256.cue',
                                  Path(folder)/str(side), side, cable, inputs))
            def observe(c):
                nonlocal benchmark_start,last_window
                now=time.perf_counter()
                actual_times=[core.word(0x895a8) for core in cores]
                if c.gameplay==30:
                    if feed and hasattr(feed,'begin'): feed.begin([core.frame+1 for core in cores])
                    benchmark_start=last_window=(now,c.gameplay,actual_times)
                if last_window and c.gameplay%30==0 and c.gameplay>30:
                    dt=now-last_window[0]
                    deltas=[(a-b)&0xffffffff for a,b in zip(actual_times,last_window[2])]
                    assert all(d==30 for d in deltas), ('Unexpected actual TM3 TIME delta',deltas)
                    windows.append(dict(tick=c.gameplay,seconds=dt,actual_time_deltas=deltas,
                                        time_units_per_s=deltas[0]/dt))
                    last_window=(now,c.gameplay,actual_times)
                if c.gameplay%100==0:
                    checkpoint=dict(tick=c.gameplay,consoles=[dict(frame=core.frame,
                        time=core.word(0x895a8), ram_sha256=hashlib.sha256(C.string_at(core.ram,16*1024*1024)).hexdigest())
                        for core in cores])
                    checkpoints.append(checkpoint)
                    print(label,json.dumps(checkpoint),flush=True)
                if c.gameplay>=ticks: c.stop()
            cable.observer=observe
            start=time.perf_counter()
            def run(core):
                try:
                    while not cable.stopped:
                        core.step()
                        if paced:
                            wait=start+core.frame/59.94-time.perf_counter()
                            if wait>0: time.sleep(wait)
                except BaseException as exc:
                    errors.append(repr(exc)); cable.stop()
            threads=[threading.Thread(target=run,args=(core,),daemon=True) for core in cores]
            for thread in threads: thread.start()
            deadline=time.monotonic()+(180 if paced else 90)
            while any(t.is_alive() for t in threads) and time.monotonic()<deadline:
                time.sleep(.1)
            cable.stop()
            for thread in threads: thread.join(12)
            assert not any(t.is_alive() for t in threads)
            elapsed=time.perf_counter()-start
            for core in cores: core.screenshot(BASE/f'reports/{label}_{core.side}.bmp')
            result=dict(label=label, elapsed_s=elapsed, cpu_budget_percent=175, input_recording=recording,
                        linked_gameplay_ticks=cable.gameplay, time_mismatches=cable.time_mismatches,
                        rng_mismatches=cable.rng_mismatches, checkpoints=checkpoints, windows=windows,
                        errors=errors,cable_error=cable.error, paced=paced, actual_wan=False,
                        complete_seven_maps=False)
            assert not errors and not cable.error, result
            assert cable.gameplay>=ticks and not cable.time_mismatches and not cable.rng_mismatches, result
            return result
        finally:
            cable.stop()
            for thread in threads: thread.join(12)
            for core in cores: core.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ticks',type=int,default=600)
    p.add_argument('--replay',action='store_true')
    p.add_argument('--paced',action='store_true')
    a=p.parse_args()
    reference=BASE/'reports/reference.json'
    expected=json.loads(reference.read_text()) if a.replay else None
    label='replay' if a.replay else 'reference'
    result=run_reference(a.ticks,replay=expected['input_recording'] if expected else None,paced=a.paced,label=label)
    if expected:
        result['per_role_full_16mib_ram_equal']=result['checkpoints']==expected['checkpoints']
    (BASE/f'reports/{label}.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ('input_recording','checkpoints','windows')},indent=2))
    if expected: assert result['per_role_full_16mib_ram_equal'], 'Replica diverged'


if __name__=='__main__':main()
