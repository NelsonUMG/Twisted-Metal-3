"""Restore the original linked pause dispatch around v10's BATCH replacement.

Input is the exact isolated Path Stamp V1, never v10/v12 or a live process.
The BATCH format, RNG/TIME checks and original pause menu remain unchanged.
This is an experimental control-flow repair, not validated live gameplay.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct

import tm3_patch_path_stamp_v1 as stamp

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'diagnostics/path_stamp_v1/SCUS_942.49.path_stamp_v1'
OUT = ROOT / 'diagnostics/link_pause_v1'
SOURCE_HASH = 'ba9ec69e001b70078695ecd9d873a14fa774cd64e9467448878213d2a0800b3e'


def at(pc):
    return 0x800 + pc - 0x80010000


def word(blob, pc):
    return struct.unpack_from('<I', blob, at(pc))[0]


def branch(op, rs, rt, pc, target):
    offset = (target - pc - 4) // 4
    assert target % 4 == 0 and -32768 <= offset <= 32767
    return op << 26 | rs << 21 | rt << 16 | (offset & 0xffff)


def jump(target):
    return 2 << 26 | ((target >> 2) & 0x3ffffff)


def build(source):
    if hashlib.sha256(source).hexdigest() != SOURCE_HASH:
        raise ValueError('Expected exact Path Stamp V1 source')
    # Keep successful BATCH v0 intact. t8 is caller-clobbered by this stub.
    # Original guards checked success, local pause, then remote pause before
    # advancing to gameplay. v10 zero-filled those local/remote guards.
    changes = {
        0x8003AA98: branch(4, 2, 0, 0x8003AA98, 0x8003AB30),
        0x8003AAA0: (0x23 << 26) | (20 << 21) | (24 << 16) | 0x8c,
        0x8003AAA8: branch(5, 24, 0, 0x8003AAA8, 0x8003AB30),
        0x8003AAB0: (0x23 << 26) | (29 << 21) | (24 << 16) | 0xa8,
        0x8003AAB8: branch(5, 24, 0, 0x8003AAB8, 0x8003AB30),
        # Original retries at AA94 used a delay slot then first transfer.
        # In BATCH AA94 is only a nop: retry must include the jal at AA90.
        0x8003AB50: branch(5, 2, 3, 0x8003AB50, 0x8003AA90),
        0x8003AB68: jump(0x8003AA90),
    }
    expected = {pc: 0 for pc in changes if pc < 0x8003AB00}
    expected[0x8003AB50] = branch(5, 2, 3, 0x8003AB50, 0x8003AA94)
    expected[0x8003AB68] = jump(0x8003AA94)
    for pc, old in expected.items():
        if word(source, pc) != old:
            raise ValueError(f'Unexpected old instruction at {pc:08X}')
    if word(source, 0x8003AA90) != 0x0C011E80:
        raise ValueError('Expected BATCH call')
    # All branch/load delay slots in the inserted guard must remain nops.
    for pc in (0x8003AA9C,0x8003AAA4,0x8003AAAC,0x8003AAB4,0x8003AABC):
        if word(source, pc) != 0:
            raise ValueError('Guard delay slot is occupied')
    result = bytearray(source)
    ips = bytearray(b'PATCH')
    for pc, new in changes.items():
        struct.pack_into('<I', result, at(pc), new)
        ips += at(pc).to_bytes(3,'big') + b'\0\4' + struct.pack('<I',new)
    ips += b'EOF'
    result, ips = bytes(result), bytes(ips)
    if stamp.replay_ips(source, ips) != result:
        raise ValueError('IPS roundtrip failed')
    allowed = {at(pc)+n for pc in changes for n in range(4)}
    differences = [n for n,(a,b) in enumerate(zip(source,result)) if a!=b]
    if not set(differences) <= allowed or len(source)!=len(result):
        raise ValueError('Unexpected byte change')
    # Original UI, BATCH code, RNG/TIME comparison and path fix are not edited.
    for lo,hi in ((0x80039FDC,0x8003A0A0),(0x8003AB78,0x8003ABD0),
                  (0x8003B398,0x8003C500),(0x80047A00,0x80047C00),
                  (0x80016EA8,0x8001746C)):
        if source[at(lo):at(hi)] != result[at(lo):at(hi)]:
            raise ValueError('Protected region changed')
    meta = {
        'status':'experimental_not_live_tested',
        'source_sha256':SOURCE_HASH,
        'candidate_sha256':hashlib.sha256(result).hexdigest(),
        'ips_sha256':hashlib.sha256(ips).hexdigest(),
        'changed_bytes':len(differences),
        'changes':[{'pc':f'0x{pc:08X}','old':f'0x{word(source,pc):08X}',
                    'new':f'0x{new:08X}'} for pc,new in changes.items()],
        'limitations':['BATCH still transfers gameplay fields before pause dispatch',
                       'Both pause directions, simultaneous pause, resume and quit require live tests',
                       'Path Stamp V1 wrap and v12 timing-shim limitations remain'],
    }
    return result,ips,meta


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--verify-only',action='store_true')
    args=p.parse_args()
    result,ips,meta=build(SOURCE.read_bytes())
    if not args.verify_only:
        files={OUT/'SCUS_942.49.link_pause_v1':result,
               OUT/'tm3_link_pause_v1_from_path_stamp.ips':ips,
               OUT/'patch_manifest.json':(json.dumps(meta,indent=2)+'\n').encode()}
        for path,payload in files.items():
            if path.exists() and path.read_bytes()!=payload:
                raise FileExistsError(f'Refusing to overwrite {path}')
        OUT.mkdir(parents=True,exist_ok=True)
        for path,payload in files.items():
            if not path.exists():
                with path.open('xb') as stream: stream.write(payload)
    print(json.dumps(meta,indent=2))


if __name__=='__main__': main()
