"""Derive an isolated interpreter-only 256 MiB CPU RAM core. Never deploy it."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'third_party/beetle-psx-libretro-c27ab27c05569575e04b25e03e87fe3220fde599'
OUT = ROOT / 'diagnostics/ram256_v1/core'


def main():
    if OUT.exists():
        raise FileExistsError('Experimental source already exists; do not overwrite it')
    shutil.copytree(SOURCE, OUT, ignore=shutil.ignore_patterns('.git', '*.o', '*.a', '*.dll', '*.exe', '*.so', '*.d', '.deps'))
    path = OUT / 'libretro.c'
    original = path.read_bytes()
    text = original.decode('utf-8')
    changes = [
        ('#define RAM_SIZE     0x1000000', '#define RAM_SIZE     0x10000000'),
        ('A < 0x01000000', 'A < 0x10000000'),
        ('MainRAM, A & 0xFFFFFF', 'MainRAM, A & 0x0FFFFFFF'),
        ('memset(MultiAccessSizeMem_get_data32(MainRAM), 0, 16 * 1024 * 1024)',
         'memset(MultiAccessSizeMem_get_data32(MainRAM), 0, 256 * 1024 * 1024)'),
        ('TextStart &= 0xFFFFFF;', 'TextStart &= 0x0FFFFFFF;'),
        ('const int DEFAULT_STATE_SIZE = 16 * 1024 * 1024;',
         'const int DEFAULT_STATE_SIZE = 260 * 1024 * 1024;'),
    ]
    counts = {}
    for old, new in changes:
        count = text.count(old)
        if not count:
            raise ValueError('Source contract changed: ' + old)
        counts[old] = count
        text = text.replace(old, new)
    path.write_bytes(text.encode('utf-8'))
    manifest = dict(status='experimental_not_deployed', cpu_ram_bytes=256 * 1024 * 1024,
        engine_reserved_start=0x01000000, engine_reserved_bytes=240 * 1024 * 1024,
        legacy_game_ram_bytes=16 * 1024 * 1024, interpreter_only=True,
        dma_legacy_24bit=True, lightrec_supported=False,
        source_sha256=hashlib.sha256(original).hexdigest(),
        candidate_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), substitutions=counts,
        production_bin_modified=False, internet_engine_complete=False)
    (OUT.parent / 'source_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__': main()
