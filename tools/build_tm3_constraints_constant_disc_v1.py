"""Package the validated constant-product candidate in an isolated raw disc."""
import hashlib
import json
import shutil
from audit_tm3_offline_bin import ROOT, disc_file
from tm3_patch_timer_recovery_v1 import encode_sector, digest
from tm3_constraints_constant_candidate_v1 import OUT, SITES, offset, build


def main():
    source=ROOT/'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin'
    executable,location=disc_file(source,'SCUS_942.49')
    candidate=build(executable)
    retained=(OUT/'SCUS_942.49.constraints_constants_v1').read_bytes()
    if candidate!=retained:raise ValueError('Retained candidate mismatch')
    target=OUT/'TM3_CONSTRAINTS_CONSTANTS_V1.bin'
    cue=target.with_suffix('.cue')
    if target.exists() or cue.exists():raise FileExistsError('Refusing candidate overwrite')
    sectors={}
    with source.open('rb') as stream:
        for pc in SITES:
            off=offset(pc);lba=location['lba']+off//2048
            if lba not in sectors:
                stream.seek(lba*2352);raw=stream.read(2352)
                if encode_sector(raw)!=raw:raise ValueError('Source EDC/ECC mismatch')
                sectors[lba]=bytearray(raw)
            within=24+off%2048
            if within+16>2072:raise ValueError('Patch crosses a sector')
            sectors[lba][within:within+16]=candidate[off:off+16]
    sectors={lba:encode_sector(raw) for lba,raw in sectors.items()}
    with source.open('rb') as src,target.open('xb') as dst:
        shutil.copyfileobj(src,dst)
    with target.open('r+b') as stream:
        for lba,raw in sectors.items():stream.seek(lba*2352);stream.write(raw)
    actual,loc=disc_file(target,'SCUS_942.49')
    if actual!=candidate or loc!=location:raise ValueError('Re-extracted SCUS mismatch')
    with source.open('rb') as src,target.open('rb') as dst:
        position=0
        while old:=src.read(1024*1024):
            expected=bytearray(old)
            for lba,raw in sectors.items():
                begin,end=lba*2352,(lba+1)*2352
                left,right=max(position,begin),min(position+len(old),end)
                if left<right:expected[left-position:right-position]=raw[left-begin:right-begin]
            if dst.read(len(old))!=expected:raise ValueError('Unexpected disc changes')
            position+=len(old)
        if dst.read(1):raise ValueError('Disc size mismatch')
    text=source.with_suffix('.cue').read_text().replace(source.name,target.name)
    with cue.open('x',encoding='ascii') as stream:stream.write(text)
    report={'status':'experimental_disc_for_offline_test','source':str(source),'candidate':str(target),
            'source_sha256':digest(source),'candidate_sha256':digest(target),
            'executable_sha256':hashlib.sha256(actual).hexdigest(),
            'changed_lbas':sorted(sectors),'edc_ecc_rebuilt':True,
            'verified_other_raw_bytes_identical':True,'packaged_files_untouched':True,
            'timer_recovery_patch_present':False}
    with (OUT/'disc_manifest.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
