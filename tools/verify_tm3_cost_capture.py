"""Freeze buffered network follow-up and verify fixed GuestCost intervals."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from analyze_tm3_link_wait import records


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture',type=Path)
    p.add_argument('run',type=Path)
    args=p.parse_args()
    result={'sides':{},'sources':{}}
    keys=[]
    for side in ('Oscar','Sofia'):
        name=f'TM3Online_{side}.rngcaller.trace.log'
        raw=(args.run/name).read_bytes()
        raw=raw[:raw.rfind(b'\n')+1]
        target=args.capture/(name+'.followup')
        with target.open('xb') as f:f.write(raw)
        source=(args.capture/f'{side}.guest_cost.csv').read_bytes()
        source=source[:source.rfind(b'\n')+1]
        ticks=list(csv.DictReader(io.StringIO(source.decode())))
        net={}
        for row in records(raw.decode(errors='replace')):
            net.setdefault(int(row['seq']),[]).append(row)
        missing=[];bad=[]
        for tick in ticks:
            seq=int(tick['sequence_before'])+1
            rs=net.get(seq,[])
            if len(rs)!=1:
                missing.append(seq);continue
            row=rs[0]
            if (row.get('sync')!='OK' or row.get('call')!='8003AA98' or
                int(row.get('local-time','-1'),16)!=int(tick['time_start']) or
                row['send_bytes']!=36 or row['recv_bytes']!=36):
                bad.append(seq)
        keys.append([(t['map'],t['time_start'],t['time_end'],t['active_start'],t['active_end']) for t in ticks])
        result['sides'][side]={'intervals':len(ticks),'first_time':ticks[0]['time_start'] if ticks else None,
                              'last_time':ticks[-1]['time_end'] if ticks else None,
                              'missing_or_duplicate_sequences':missing,'bad_sequences':bad,
                              'mismatch_lines_in_followup':sum(b'MISMATCH' in line for line in raw.splitlines())}
    result['identical_time_and_population_intervals']=keys[0]==keys[1]
    result['verified']=bool(keys[0]) and keys[0]==keys[1] and all(not r['missing_or_duplicate_sequences'] and not r['bad_sequences'] for r in result['sides'].values())
    for path in sorted(args.capture.iterdir()):
        if path.is_file():
            raw=path.read_bytes()
            result['sources'][path.name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    with (args.capture/'verification.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='sources'},indent=2))


if __name__=='__main__':main()
