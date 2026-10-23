"""Experimental SCUS-only specialization of three constant rounded products.

No disc deployment. Input/output files are isolated from the packaged game.
For signed b and m=512/1024, round((m*b)/4096) equals
floor(b/2**k) + bit(k-1,b), k=3/2, including signed extremes.
"""
import hashlib
import json
from pathlib import Path
import struct
from audit_tm3_offline_bin import ROOT, EXPECTED, disc_file, word

SITES={0x8001FCA8:(0x200,3),0x8001FD20:(0x400,2),0x8001FDA0:(0x200,3)}
OUT=ROOT/'diagnostics/constraints_constant_candidate_v1'


def offset(pc):return 0x800+pc-0x80010000


def replacement(k):
    # v0 input/output; v1 temporary, dead at each site until overwritten.
    return [2<<16|3<<11|k<<6|3, 2<<16|2<<11|(k-1)<<6|2,
            12<<26|2<<21|2<<16|1, 3<<21|2<<16|2<<11|0x21]


def build(source):
    if hashlib.sha256(source).hexdigest()!=EXPECTED:
        raise ValueError('Exact audited V4 required')
    candidate=bytearray(source)
    for pc,(constant,k) in SITES.items():
        expected=[0x24040000|constant,0x00402821,0x0C0055A1,0x2406000C]
        if [word(source,pc+4*i) for i in range(4)]!=expected:
            raise ValueError(f'Unexpected code at {pc:08X}')
        struct.pack_into('<4I',candidate,offset(pc),*replacement(k))
    return bytes(candidate)


def main():
    source,_=disc_file(ROOT/'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin','SCUS_942.49')
    candidate=build(source)
    OUT.mkdir(exist_ok=False)
    (OUT/'SCUS_942.49.constraints_constants_v1').write_bytes(candidate)
    manifest={'status':'experimental_SCUS_only_not_deployed',
              'source_sha256':hashlib.sha256(source).hexdigest(),
              'candidate_sha256':hashlib.sha256(candidate).hexdigest(),
              'sites':{f'{pc:08X}':{'constant':c,'shift':k} for pc,(c,k) in SITES.items()},
              'scope':'Three 16-byte blocks only. No timer/render/RNG changes.',
              'limits':'Arithmetic/window equivalence is not full-game, interrupt, timing or synchronization proof.'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
