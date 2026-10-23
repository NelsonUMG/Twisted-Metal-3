"""Trim two dispatches from general sqrt entry; preserve FastV2 arithmetic."""
import json
import struct
import tm3_patch_sqrt_pair_v1 as base

ROOT=base.ROOT
SOURCE=ROOT/'diagnostics/sqrt_fast_v2/SCUS_942.49.sqrt_fast_v2'
SOURCE_HASH='c70e4974fde73bfb430cac1440d15c2262a003e7a95f21ba137a6e61604226be'
OUT=ROOT/'diagnostics/sqrt_dispatch_v3'

def build(source):
    if base.digest(source)!=SOURCE_HASH:raise ValueError('Exact FastV2 source required')
    # Skip the ANDI at helper entry, executing it in the existing hook delay.
    # At fallback move the v0 initialization to the jump delay instead of NOP.
    edits={
        0x80013C3C:(base.jump(0x80047B50),base.jump(0x80047B54)),
        0x80013C40:(0,base.imm(12,6,10,1)),
        0x800478E4:(0x24020000,base.jump(0x80013C08)),
        0x800478E8:(base.jump(0x80013C08),0x24020000),
    }
    # Refuse direct entries into the changed delay slots. Indirect entries
    # cannot be exhaustively excluded by static scanning; gameplay remains pending.
    for pc in range(0x80010000,0x8007F000,4):
        w=base.word(source,pc);op=w>>26;target=None
        if op in (2,3):target=((pc+4)&0xf0000000)|((w&0x3ffffff)<<2)
        elif op in (1,4,5,6,7):
            n=w&65535;target=pc+4+4*(n-65536 if n&32768 else n)
        if target in (0x80013C40,0x800478E8):raise ValueError('Direct entry into delay slot')
    for off in range(0x800,len(source)-3,4):
        if struct.unpack_from('<I',source,off)[0] in (0x80013C40,0x800478E8):
            raise ValueError('Embedded pointer into delay slot')
    candidate=bytearray(source);ips=b'PATCH'
    for pc,(expected,new) in edits.items():
        if base.word(source,pc)!=expected:raise ValueError('Unexpected instruction')
        data=struct.pack('<I',new);offset=base.at(pc)
        candidate[offset:offset+4]=data
        ips+=offset.to_bytes(3,'big')+b'\x00\x04'+data
    candidate=bytes(candidate);ips+=b'EOF'
    if base.replay_ips(source,ips)!=candidate:raise ValueError('IPS mismatch')
    return candidate,ips,{'format':'TM3_SQRT_DISPATCH_V3_PATCH',
        'source_sha256':base.digest(source),'candidate_sha256':base.digest(candidate),
        'ips_sha256':base.digest(ips),'instruction_addresses':[f'{p:08X}' for p in edits],
        'status':'experimental_gameplay_AB_pending',
        'scope':'Four instruction words only. Fast path unchanged; general entry saves two dispatches.',
        'limits':'Return-state replay is not interrupt equivalence or whole-game synchronization proof. No measured speedup.'}

def main():
    candidate,ips,meta=build(SOURCE.read_bytes());OUT.mkdir(parents=True,exist_ok=True)
    for name,data in [('SCUS_942.49.sqrt_dispatch_v3',candidate),('sqrt_dispatch_v3.ips',ips),
                      ('patch_manifest.json',(json.dumps(meta,indent=2)+'\n').encode())]:
        path=OUT/name
        if path.exists():
            if path.read_bytes()!=data:raise FileExistsError(path)
        else:
            with path.open('xb') as stream:stream.write(data)
    print(json.dumps(meta,indent=2))

if __name__=='__main__':main()
