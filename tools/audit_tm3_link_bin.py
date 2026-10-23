"""Read-only binary/network audit; freezes evidence, never touches a process."""
import argparse
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
import tm3_patch_network as network
from analyze_tm3_link_wait import records

def timing(rows):
    if not rows:return {'count':0}
    before=[max(0,r['ready_us']-r['observed_us']) for r in rows]
    after=[max(0,r['wait_us']-b) for r,b in zip(rows,before)]
    return {'count':len(rows),'first_seq':rows[0]['seq'],'last_seq':rows[-1]['seq'],
        'wait_mean_ms':sum(r['wait_us'] for r in rows)/len(rows)/1000,
        'before_remote_ready_mean_ms':sum(before)/len(rows)/1000,
        'after_remote_ready_mean_ms':sum(after)/len(rows)/1000,
        'retries':sum(r['retries'] for r in rows),
        'payload_sizes':sorted({(r['send_bytes'],r['recv_bytes']) for r in rows})}

def audit(run,scus,out):
    blob=scus.read_bytes();expected=network.build_gameplay_batch_transfer()
    off=0x800+network.GAMEPLAY_BATCH_FUNCTION-network.TEXT_ADDRESS
    actual=blob[off:off+len(expected)]
    if actual!=expected:raise ValueError('BATCH differs from audited assembler; review before proceeding')
    out.mkdir(parents=True,exist_ok=False)
    report={'scus':str(scus.resolve()),'scus_sha256':hashlib.sha256(blob).hexdigest(),
        'batch_matches_generator':True,'batch_bytes':len(expected),
        'batch_sha256':hashlib.sha256(actual).hexdigest(),'sides':{},
        'limitations':['Host timing is not pure RTT or guest cycles.',
            'Before-ready includes peer computation, scheduling and transport.',
            'After-ready ends before status publication, not at guest resumption.',
            'Last 500 successful gameplay records are not a controlled eight-vehicle scene.',
            'Frozen prefixes exclude incomplete lines; no process memory accessed.']}
    for side in ('Oscar','Sofia'):
        name=f'TM3Online_{side}.rngcaller.trace.log'
        raw=(run/name).read_bytes();raw=raw[:raw.rfind(b'\n')+1]
        (out/name).write_bytes(raw)
        allrows=records(raw.decode('utf-8-sig',errors='replace'))
        gameplay=[r for r in allrows if r.get('call')=='8003AA98' and r.get('sync')=='OK'][-500:]
        report['sides'][side]={'source_sha256':hashlib.sha256(raw).hexdigest(),
            'mismatches':sum(r.get('sync') in ('TIME_MISMATCH','RANDOM_MISMATCH') for r in allrows),
            'recent_gameplay':timing(gameplay)}
    (out/'analysis.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('scus',type=Path)
    a=p.parse_args();out=a.run/('link_bin_audit_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    print(json.dumps(audit(a.run,a.scus,out),indent=2));print(out)
