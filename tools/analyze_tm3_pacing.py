"""Freeze complete records and summarize guest-cycle phases, not wall time/FPS."""
import argparse
import csv
import hashlib
import io
import json
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from analyze_tm3_link_wait import records

MARKS=['publish','link_return','world_done','gate_entry','gate_ready','render_done','cycles']
PHASES=['publish_setup','link_wait_return','world_update','render_before_gate','gate_wait','presentation_after_gate','tail']

def summarize(rows):
    if not rows:return {'intervals':0}
    totals=[0]*7
    for r in rows:
        values=[0]+[r[k] for k in MARKS]
        for i in range(7):totals[i]+=values[i+1]-values[i]
    total=sum(totals)
    return {'intervals':len(rows),'time_first':rows[0]['time_start'],'time_last':rows[-1]['time_end'],
            'guest_cycles_mean':total/len(rows),'core_boundary_crossings_mean':sum(r['frames'] for r in rows)/len(rows),
            'phase_guest_cycles_mean':dict(zip(PHASES,[v/len(rows) for v in totals])),
            'phase_guest_cycle_percent':dict(zip(PHASES,[100*v/total if total else 0 for v in totals])),
            'gate_entry_counter_counts':dict(Counter(r['entry_counter'] for r in rows)),
            'gate_target_counts':dict(Counter(r['target_counter'] for r in rows)),
            'gate_entry_already_at_target':sum(r['entry_counter']>=r['target_counter'] for r in rows),
            'gate_entry_signal_zero':sum(r['entry_signal']==0 for r in rows),
            'gate_release_counter_counts':dict(Counter(r['release_counter'] for r in rows))}

def parse(raw):
    rows=[]
    for row in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
        if None in row or any(v is None for v in row.values()):raise ValueError('Malformed complete row')
        r={k:int(v) for k,v in row.items()}
        if r['valid']:
            values=[0]+[r[k] for k in MARKS]
            if r['mask']!=63 or r['time_end']!=r['time_start']+1 or values!=sorted(values):
                raise ValueError('Invalid interval marked valid')
        rows.append(r)
    return rows

def capture(run,out):
    out.mkdir(parents=True,exist_ok=False)
    result={'run':str(run.resolve()),'sides':{},'sources':{},'limitations':[
        'Cycle spans include IRQ/events and are not exclusive CPU instructions or host wall time.',
        'Sparse observer adds host overhead and can alter peer scheduling; not a speed acceptance benchmark.',
        'Population/pause validity uses interval endpoints, not every instant; scenes are grouped separately.',
        'A gate counter at/above target does not establish whether render, world or link caused it.',
        'The core timestamp can be rebased between slices; frame hooks accumulate those spans.',
        'No guest state writes or change to frame regulator. Last unfinished interval is absent.']}
    for side in ('Oscar','Sofia'):
        frozen={}
        for name in (side+'.pacing.csv','TM3Online_'+side+'.rngcaller.trace.log'):
            raw=(run/name).read_bytes();end=raw.rfind(b'\n')+1;raw=raw[:end]
            (out/name).write_bytes(raw);frozen[name]=raw
            result['sources'][name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        rows=parse(frozen[side+'.pacing.csv']);net=defaultdict(list)
        for n in records(frozen['TM3Online_'+side+'.rngcaller.trace.log'].decode('utf-8-sig',errors='replace')):
            if 'seq' in n:net[int(n['seq'])].append(n)
        groups=defaultdict(list);rejected=Counter()
        for r in rows:
            if not r['valid']:rejected['invalid_scene_or_marks']+=1;continue
            ns=net[r['sequence_before']+1]
            if len(ns)!=1:rejected['missing_or_duplicate_network_record']+=1;continue
            n=ns[0]
            if (n.get('sync')!='OK' or n.get('call')!='8003AA98' or
                int(n.get('local-time','-1'),0)!=r['time_start'] or
                n['send_bytes']!=36 or n['recv_bytes']!=36):
                rejected['network_check_failed']+=1;continue
            groups[f"map{r['map']}_active{r['active_start']}"] .append(r)
        result['sides'][side]={'complete_rows':len(rows),'excluded':dict(rejected),
                               'groups':{k:summarize(v) for k,v in groups.items()}}
    (out/'analysis.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--output',type=Path)
    args=p.parse_args();out=args.output or args.run/('pacing_capture_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    print(json.dumps(capture(args.run,out),indent=2))
