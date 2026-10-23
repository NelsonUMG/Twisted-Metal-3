"""Read-only audit of the linked pause regression and the completed user run."""
import hashlib
import json
import re
from pathlib import Path
import tm3_patch_link_pause_v1 as patch

ROOT=patch.ROOT
RUN=ROOT/'diagnostics/path_stamp_v1/runs/PathStampV1_20261007_214701_168_198993be'


def audit():
    original=(ROOT/'TM3_EXTRAIDO/SCUS_942.49.menu_only_backup').read_bytes()
    if hashlib.sha256(original).hexdigest()!='24fc2707d63ceaab857105c6b9bbf1e344054ace116c97d538c478310ba4d765':
        raise ValueError('Unexpected original reference')
    source=patch.SOURCE.read_bytes()
    candidate,_,meta=patch.build(source)
    guards={0x8003AAAC:0x8E82008C,0x8003AAB4:0x1440001E,
            0x8003AABC:0x8FA200A8,0x8003AAC4:0x1440001A}
    for pc,expected in guards.items():
        if patch.word(original,pc)!=expected or patch.word(source,pc)!=0:
            raise ValueError(f'Original guard/removal mismatch at {pc:08X}')
    evidence={'status':'static_cause_and_completed_run_not_candidate_live_test',
              'original_pause_guards_zeroed_by_batch':True,
              'candidate_patch':meta,'run':str(RUN),'logs':{}}
    for side in ('Oscar','Sofia'):
        path=RUN/f'TM3Online_{side}.rngcaller.trace.log'
        data=path.read_bytes()
        lines=data.decode('utf-8',errors='replace').splitlines()
        tx=[line for line in lines if line.startswith('TX ') and 'call=8003AA98' in line]
        paused=[line for line in tx if re.search(r'\bword=[1-9]\d*\b',line)]
        mismatches=[line for line in lines if 'sync=RANDOM_MISMATCH' in line or 'sync=TIME_MISMATCH' in line]
        evidence['logs'][side]={
            'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
            'batch_tx_records':len(tx),'last_batch_tx':tx[-1] if tx else None,
            'nonzero_pause_word_count':len(paused),
            'first_nonzero_pause_word':paused[0] if paused else None,
            'last_nonzero_pause_word':paused[-1] if paused else None,
            'mismatch_records':len(mismatches),'first_mismatch':mismatches[0] if mismatches else None,
        }
    return evidence


if __name__=='__main__':
    report=json.dumps(audit(),indent=2)+'\n'
    (ROOT/'diagnostics/link_pause_v1/pause_audit.json').write_text(report,encoding='utf-8')
    print(report)
