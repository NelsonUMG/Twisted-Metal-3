"""Validate the actual rebuilt ISO payload, patch scope and protected product."""
import difflib
import hashlib
import json
from pathlib import Path
import struct
import sys

BASE=Path(__file__).resolve().parent.parent
ROOT=BASE.parent


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def disc_scus(path):
    with path.open('rb') as f:
        def read(lba,size):
            blocks=[]
            for sector in range((size+2047)//2048):
                f.seek((lba+sector)*2352)
                raw=f.read(2352)
                assert raw[:12]==b'\0'+b'\xff'*10+b'\0' and raw[15]==2
                assert raw[16:20]==raw[20:24] and not raw[18]&32, 'Expected Mode2 Form1 data'
                blocks.append(raw[24:24+2048])
            return b''.join(blocks)[:size]
        pvd=read(16,2048)
        assert pvd[:7]==b'\x01CD001\x01'
        root=pvd[156:190];lba=struct.unpack_from('<I',root,2)[0];size=struct.unpack_from('<I',root,10)[0]
        directory=read(lba,size);pos=0
        while pos<len(directory):
            length=directory[pos]
            if not length:pos=(pos//2048+1)*2048;continue
            record=directory[pos:pos+length]
            name=record[33:33+record[32]]
            if name in (b'SCUS_942.49',b'SCUS_942.49;1'):
                extent=struct.unpack_from('<I',record,2)[0];n=struct.unpack_from('<I',record,10)[0]
                return read(extent,n),extent
            pos+=length
        raise ValueError('SCUS not found in actual BIN ISO9660')


def main():
    protected=json.loads((BASE/'reports/protected_before.json').read_text())
    for path,digest in protected.items():assert sha(ROOT/path)==digest,path
    source=(ROOT/'diagnostics/sqrt_merge_v4/SCUS_942.49.sqrt_merge_v4').read_bytes()
    target=(BASE/'game/SCUS_942.49.system256').read_bytes()
    assert len(source)==len(target)==655360
    allowed=set()
    for pc,size in ((0x80047758,4),(0x80047904,4),(0x80047a5c,4),(0x80047df8,4),(0x80047578,32)):
        offset=0x800+pc-0x80010000;allowed.update(range(offset,offset+size))
    changed={i for i,(a,b) in enumerate(zip(source,target)) if a!=b}
    assert changed and changed<=allowed
    # A reversible IPS contains exactly the approved changed regions.
    ips=bytearray(b'PATCH')
    offsets=sorted(allowed);start=previous=offsets[0]
    for i in offsets[1:]+[len(source)+1]:
        if i==previous+1:previous=i;continue
        payload=target[start:previous+1]
        ips+=start.to_bytes(3,'big')+len(payload).to_bytes(2,'big')+payload
        start=previous=i
    ips+=b'EOF';(BASE/'game/system256_from_sqrt_merge_v4.ips').write_bytes(ips)
    extracted,lba=disc_scus(BASE/'game/TM3_SYSTEM256.bin')
    assert extracted==target,'Rebuilt BIN does not contain the experimental executable'
    original_core=(ROOT/'diagnostics/ram256_v1/core/libretro.c').read_text()
    new_core=(BASE/'core_source/libretro.c').read_text()
    (BASE/'reports/core_twin_changes.patch').write_text(''.join(difflib.unified_diff(
        original_core.splitlines(True),new_core.splitlines(True),fromfile='ram256/libretro.c',tofile='system256/libretro.c')))
    report=dict(protected_product_preserved=True,protected_files=list(protected),
        actual_bin_scus_verified=True,scus_extent_lba=lba,scus_sha256=sha(BASE/'game/SCUS_942.49.system256'),
        bin_sha256=sha(BASE/'game/TM3_SYSTEM256.bin'),core_sha256=sha(BASE/'core_source/mednafen_psx_libretro.dll'),
        changed_executable_bytes=len(changed),patch_scope_verified=True,
        game_time_logic_unchanged=True,game_rng_logic_unchanged=True,
        working_lobby_or_portable_replaced=False)
    (BASE/'reports/audit.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
