"""Freeze detailed guest-cycle ledgers and verify network-aligned intervals."""
import argparse
import csv
import hashlib
import io
import json
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from analyze_tm3_link_wait import records
from analyze_tm3_pacing import PHASES

ROOT=Path(__file__).resolve().parents[1]
HIST_KEYS=('functions','phases','classes','render_pcs')
CLASSES=['other_integer_control','cop2_lwc2_swc2','load_store','muldiv_hilo','irq_dispatch']
HIST_LIMITS={'functions':1133,'phases':7,'classes':5,'render_pcs':(0x800115C4-0x80010B1C)//4}

def hist(text):
    result={}
    for item in text.split(';'):
        if not item:continue
        v=list(map(int,item.split(':')))
        if len(v)!=5 or min(v)<0 or v[0] in result or v[4]>v[3]:raise ValueError('Invalid histogram')
        result[v[0]]=v[1:]
    return result

def total(h):return [sum(v[i] for v in h.values()) for i in range(4)]

def parse(raw):
    rows=[];previous=0
    for text in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
        if None in text or any(v is None for v in text.values()):raise ValueError('Malformed complete row')
        r={k:int(v) for k,v in text.items() if k not in HIST_KEYS+('callbacks',)}
        if r['tick']!=previous+1:raise ValueError('Nonconsecutive ticks')
        previous=r['tick']
        for k in HIST_KEYS:
            r[k]=hist(text[k])
            if any(i>=HIST_LIMITS[k] for i in r[k]):raise ValueError('Histogram ID out of range')
        if not total(r['functions'])==total(r['phases'])==total(r['classes']):raise ValueError('Ledgers disagree')
        r['callbacks']={}
        for item in text['callbacks'].split(';'):
            if not item:continue
            parts=item.split(':');key=tuple(int(v,16) for v in parts[:2]);v=list(map(int,parts[2:]))
            if len(v)!=5 or min(v)<0 or v[4]>v[3] or key in r['callbacks']:raise ValueError('Invalid callback')
            r['callbacks'][key]=v
        if r['valid'] and (r['time_end']!=r['time_start']+1 or r['active_start']!=r['active_end']):raise ValueError('Invalid state marked valid')
        rows.append(r)
    return rows

def summarize(rows,labels):
    totals={k:defaultdict(lambda:[0]*4) for k in HIST_KEYS}
    callbacks=defaultdict(lambda:[0]*5)
    for r in rows:
        for k in HIST_KEYS:
            for identity,values in r[k].items():totals[k][identity]=[a+b for a,b in zip(totals[k][identity],values)]
        for key,v in r['callbacks'].items():callbacks[key]=[a+b for a,b in zip(callbacks[key],v)]
    dispatches,fetch,execution,gte=total(totals['functions']);cycles=fetch+execution
    def ranking(key,names,limit=None):
        values=sorted(totals[key].items(),key=lambda item:item[1][1]+item[1][2],reverse=True)
        return [{'name':names(i),'dispatches':v[0],'fetch_cycles':v[1],'execution_cycles':v[2],
                 'gte_wait_cycles_subset':v[3],'percent_accounted_cycles':100*(v[1]+v[2])/cycles if cycles else 0}
                for i,v in values[:limit]]
    span=sum(r['span_cycles'] for r in rows)
    return {'intervals':len(rows),'first_time':rows[0]['time_start'],'last_time':rows[-1]['time_end'],
        'span_cycles':span,'accounted_fetch_plus_execution':cycles,'event_or_unaccounted_cycles':span-cycles,
        'dispatches':dispatches,'fetch_cycles':fetch,'execution_cycles':execution,'gte_wait_cycles_subset':gte,
        'fast_calls':sum(r['fast_calls'] for r in rows),'fallback_calls':sum(r['fallback_calls'] for r in rows),
        'primitive_visits':sum(r['primitive_visits'] for r in rows),'rtpt_dispatches':sum(r['rtpt_dispatches'] for r in rows),
        'callback_overflow':sum(r['callback_overflow'] for r in rows),
        'functions':ranking('functions',lambda i:labels[i],25),
        'phases':ranking('phases',lambda i:PHASES[i]),'classes':ranking('classes',lambda i:CLASSES[i]),
        'render_pcs':ranking('render_pcs',lambda i:f'{0x80010B1C+4*i:08X}',30),
        'callbacks_top_inclusive':[{'target':f'{k[0]:08X}','object':f'{k[1]:08X}','calls':v[0],
            'dispatches':v[1],'fetch_cycles':v[2],'execution_cycles':v[3],'gte_wait_cycles_subset':v[4]}
            for k,v in sorted(callbacks.items(),key=lambda item:item[1][2]+item[1][3],reverse=True)[:25]]}

def capture(run,out):
    labels=json.loads((ROOT/'diagnostics/guest_cost_v1/function_ids.json').read_text())+['sqrt_pair_v1','sqrt_fast_v2']
    out.mkdir(parents=True,exist_ok=False)
    result={'run':str(run.resolve()),'sides':{},'sources':{},'limitations':[
        'Fetch and execution timestamp deltas are guest cycles, not Intel time or retired instruction counts.',
        'GTE wait is a measured subset of execution, never additive. Callbacks are inclusive subsets.',
        'Execution includes data-memory/MMIO waits. GPU-only stalls are not independently isolated.',
        'External event-handler cycles appear as residual; investigate unexpected residual before conclusions.',
        'Phase assignment uses first marks; function names come from a PC map. No automatic bottleneck verdict.',
        'Detailed observer changes host load and peer readiness; not a performance acceptance benchmark.']}
    for side in ('Oscar','Sofia'):
        frozen={}
        for name in (side+'.cycle_detail.csv','TM3Online_'+side+'.rngcaller.trace.log'):
            raw=(run/name).read_bytes();raw=raw[:raw.rfind(b'\n')+1];frozen[name]=raw;(out/name).write_bytes(raw)
            result['sources'][name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        rows=parse(frozen[side+'.cycle_detail.csv']);net=defaultdict(list)
        for n in records(frozen['TM3Online_'+side+'.rngcaller.trace.log'].decode('utf-8-sig',errors='replace')):
            if 'seq' in n:net[int(n['seq'])].append(n)
        groups=defaultdict(list);excluded=Counter()
        for r in rows:
            if not r['valid']:excluded['invalid_scene']+=1;continue
            ns=net[r['sequence_before']+1]
            if len(ns)!=1:excluded['missing_duplicate_network']+=1;continue
            n=ns[0]
            if (n.get('sync')!='OK' or n.get('call')!='8003AA98' or int(n.get('local-time','-1'),0)!=r['time_start']
                or n['send_bytes']!=36 or n['recv_bytes']!=36):excluded['network_failed']+=1;continue
            groups[f"map{r['map']}_active{r['active_start']}"] .append(r)
        result['sides'][side]={'complete_rows':len(rows),'excluded':dict(excluded),'groups':{k:summarize(v,labels) for k,v in groups.items()}}
    (out/'analysis.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--output',type=Path)
    args=p.parse_args();out=args.output or args.run/('cycle_capture_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    print(json.dumps(capture(args.run,out),indent=2))
