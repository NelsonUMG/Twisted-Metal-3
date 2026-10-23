"""Disassemble bounded physics candidates from the verified current disc."""
import csv
import argparse
import json
from pathlib import Path
import sys
from audit_tm3_offline_bin import ROOT, EXPECTED, disc_file, sha, word


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'diagnostics/offline_world_profile_v1/static_candidates_v2')
    args=parser.parse_args()
    sys.path.insert(0,str(ROOT/'.codex_tmp_capstone'))
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
    blob,location=disc_file(ROOT/'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin','SCUS_942.49')
    assert sha(blob)==EXPECTED
    decoder=Cs(CS_ARCH_MIPS,CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
    ownership={int(r['pc'],16):r['function_name'] for r in csv.DictReader((ROOT/'diagnostics/tm3_profile_pcmap_v20.csv').open())}
    starts=[0x800211D4,0x8001E470,0x800210F8,0x8001F784,0x80015684,
            0x800155A4,0x80014B6C,0x800148DC,0x80014AD4,0x80013D64,
            0x8001E49C,0x800154EC]
    output=args.output
    output.mkdir(exist_ok=False)
    report={'executable_sha256':sha(blob),'iso_file':location,'functions':{},
            'method':'Current disc bytes; historical Ghidra PC ownership as bounds/labels; per-word Capstone decode.'}
    for start in starts:
        label=ownership[start]
        pcs=sorted(pc for pc,owner in ownership.items() if owner==label)
        assert min(pcs)==start and all(start<=pc<start+0x4000 for pc in pcs)
        end=max(pcs)+4
        lines=[];calls=[]
        for pc in range(start,end,4):
            w=word(blob,pc)
            ins=list(decoder.disasm(w.to_bytes(4,'little'),pc,count=1))
            text=(ins[0].mnemonic+' '+ins[0].op_str) if ins else '.word (GTE/undecoded)'
            lines.append(f'{pc:08X}  {w:08X}  {text}')
            if w>>26==3:
                calls.append({'site':f'{pc:08X}','target':f'{((pc+4)&0xF0000000)|((w&0x3FFFFFF)<<2):08X}'})
        (output/(label+'.asm')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
        report['functions'][f'{start:08X}']={'label':label,'start':f'{start:08X}',
              'end_exclusive':f'{end:08X}','calls':calls}
    (output/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
