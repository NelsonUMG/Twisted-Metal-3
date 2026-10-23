"""Generate exact-PC ownership for the diagnostic core (mechanical output)."""
import csv
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'diagnostics/guest_cost_v1'
labels = ['outside_text', 'unmapped', 'BATCH_stub', 'DIRECT_stub']
ids = {}
table = [1] * ((0x80070000-0x80010000)//4)
for row in csv.DictReader((ROOT/'diagnostics/tm3_profile_pcmap_v20.csv').open()):
    name = row['function_name']
    if name not in ids:
        ids[name] = len(labels)
        labels.append(name)
    pc = int(row['pc'], 16)
    if 0x80010000 <= pc < 0x80070000:
        table[(pc-0x80010000)//4] = ids[name]
for lo, hi, ident in ((0x80047A00,0x80047B4C,2), (0x80047728,0x80047900,3)):
    for pc in range(lo, hi, 4):
        table[(pc-0x80010000)//4] = ident
header = '#define TM3O_COST_FUNCTIONS %d\nstatic const uint16_t tm3o_cost_map[] = {\n' % len(labels)
header += ',\n'.join(','.join(map(str, table[i:i+32])) for i in range(0,len(table),32))+'\n};\n'
(OUT/'core/mednafen/psx/tm3o_cost_map.h').write_text(header)
(OUT/'function_ids.json').write_text(json.dumps(labels, indent=2))
print('Generated', len(table), 'PC mappings and', len(labels), 'IDs')
