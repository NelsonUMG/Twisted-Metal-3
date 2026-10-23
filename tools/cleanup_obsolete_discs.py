"""Remove explicitly retired test images, retaining verified compact recovery patches.

The active release and original reference disc are never targets. Recovery needs
the unchanged active BIN plus the ZIP patch; no game assets are downloaded.
"""
from pathlib import Path
import hashlib
import json
import zipfile
import shutil

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / 'TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin'
OUT = ROOT / 'docs/cleanup_20261021'
EXPECTED = 'ebaf1eaa5d43ddfd3c88a860f0205482dede4ee20aebe5555b2d65b0a1bff14c'
BLOCK = 65536
NAMES = ('TM3_AI_OWNER_V19', 'TM3_AI_OWNER_V19B', 'TM3_COSMETIC_RNG_V13',
         'TM3_LOCAL_RNG_V14', 'TM3_LOCAL_RNG_V15', 'TM3_LOCAL_RNG_V16',
         'TM3_ONLINE', 'TM3_ONLINE.control_batch_v11', 'TM3_ONLINE.load_delay_bug_v7',
         'TM3_ONLINE.payload_load_delay_fixed_v8', 'TM3_ONLINE.role_load_delay_fixed_v9',
         'TM3_RNGCALLER_DIAG')

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def safe(path):
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(ROOT) or resolved == ROOT or path.is_symlink():
        raise RuntimeError(f'Unsafe cleanup target: {path}')
    return resolved

def main():
    assert digest(BASE) == EXPECTED
    OUT.mkdir(exist_ok=False)
    manifest = {'base': str(BASE.relative_to(ROOT)), 'base_sha256': EXPECTED,
                'removed': [], 'bytes_removed': 0}
    def record(path, recovery):
        manifest['removed'].append(dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size,
                                       sha256=digest(path), recovery=recovery))
        manifest['bytes_removed'] += path.stat().st_size
        (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        safe(path).unlink()
    targets = [ROOT / (name + '.bin') for name in NAMES]
    for folder in ('game', 'game_rngcaller', 'game_v13', 'game_v14', 'game_v15', 'game_v16', 'game_v19', 'game_v19b'):
        targets.extend(sorted((ROOT / 'frontend/build/Release' / folder).glob('*.bin')))
    for index, path in enumerate(targets):
        if not path.exists():
            continue
        safe(path)
        assert path.stat().st_size == BASE.stat().st_size, path
        patch = OUT / f'disc_{index:02}.zip'
        original_hash = digest(path)
        with zipfile.ZipFile(patch, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            with BASE.open('rb') as base, path.open('rb') as old:
                block = 0
                while data := old.read(BLOCK):
                    if data != base.read(BLOCK):
                        archive.writestr(f'blocks/{block}', data)
                    block += 1
            archive.writestr('metadata.json', json.dumps(dict(path=str(path.relative_to(ROOT)),
                sha256=original_hash, base_sha256=EXPECTED, block_size=BLOCK, size=path.stat().st_size)))
            for suffix in ('.cue', '.xml', '.lba'):
                sibling = path.with_suffix(suffix)
                if sibling.exists():
                    archive.write(sibling, 'sidecars/' + sibling.name)
        # Independently reconstruct the hash from the saved patch before deletion.
        restored = hashlib.sha256()
        with zipfile.ZipFile(patch) as archive, BASE.open('rb') as base:
            names = set(archive.namelist())
            block = 0
            while data := base.read(BLOCK):
                member = f'blocks/{block}'
                restored.update(archive.read(member) if member in names else data)
                block += 1
        assert restored.hexdigest() == original_hash, path
        record(path, str(patch.relative_to(ROOT)))
        for suffix in ('.cue', '.xml', '.lba'):
            sibling = path.with_suffix(suffix)
            if sibling.exists():
                record(sibling, str(patch.relative_to(ROOT)))
        print(f'Removed {path.relative_to(ROOT)}; verified recovery {patch.stat().st_size:,} bytes', flush=True)
    # Extracted audit copies: retain unique files, reference identical preserved assets.
    for name in ('.codex_tmp_bin_audit_v7', '.codex_tmp_bin_audit_v8', '.codex_tmp_bin_audit_v9'):
        directory = ROOT / name
        if not directory.exists():
            continue
        safe(directory)
        recovery = OUT / (name + '.zip')
        files = sorted(p for p in directory.rglob('*') if p.is_file())
        references = {}
        with zipfile.ZipFile(recovery, 'x', zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                safe(path)
                rel = path.relative_to(directory)
                source = ROOT / 'TM3_EXTRAIDO' / rel
                if source.is_file() and digest(source) == digest(path):
                    references[rel.as_posix()] = str(source.relative_to(ROOT))
                else:
                    archive.write(path, rel.as_posix())
            archive.writestr('RECOVERY_REFERENCES.json', json.dumps(references, indent=2))
        with zipfile.ZipFile(recovery) as archive:
            assert archive.testzip() is None
            for path in files:
                rel = path.relative_to(directory).as_posix()
                restored = digest(ROOT / references[rel]) if rel in references else hashlib.sha256(archive.read(rel)).hexdigest()
                assert restored == digest(path)
        for path in files:
            record(path, str(recovery.relative_to(ROOT)))
        # Files have been individually validated and removed; only empty dirs remain.
        for child in sorted(directory.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            safe(child).rmdir()
        safe(directory).rmdir()
        print(f'Removed verified audit copy {name}', flush=True)
    assert digest(BASE) == EXPECTED
    manifest['recovery_bytes'] = sum(p.stat().st_size for p in OUT.glob('*.zip'))
    manifest['net_bytes_freed'] = manifest['bytes_removed'] - manifest['recovery_bytes']
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'removed'}, indent=2))

if __name__ == '__main__':
    main()
