"""Import an existing local game/runtime and self-contained Python installation.

Only local ignored files are populated. No game, BIOS or personal data is pushed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def copy_verified(source, target):
    if not source.is_file(): raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if digest(source) != digest(target): raise ValueError('Copy verification failed: ' + str(target))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--installation', type=Path, required=True)
    parser.add_argument('--python-base', type=Path, required=True)
    parser.add_argument('--python-environment', type=Path, required=True)
    parser.add_argument('--original-game', type=Path)
    args = parser.parse_args()
    for name in ('runtime', '.python'):
        if (ROOT/name).exists(): raise FileExistsError('Preserve existing local files: ' + str(ROOT/name))
    source = args.installation.resolve()
    expected = json.loads((source/'RELEASE_FILES.json').read_text(encoding='utf-8'))
    for name, sha in expected['system256'].items():
        path = source/'runtime/system256'/name
        if path.parent.resolve() != (source/'runtime/system256').resolve() or digest(path) != sha:
            raise ValueError('Original runtime manifest mismatch: ' + name)
    shutil.copytree(source/'runtime', ROOT/'runtime')
    count = 0
    for path in (source/'runtime').rglob('*'):
        if path.is_file():
            relative = path.relative_to(source/'runtime')
            if digest(path) != digest(ROOT/'runtime'/relative): raise ValueError(str(relative))
            count += 1
    for name in ('RELEASE_FILES.json', 'TM3Lobby.json'):
        copy_verified(source/name, ROOT/name)
    shutil.copytree(source/'licenses', ROOT/'licenses', dirs_exist_ok=True)
    python_target = ROOT/'.python'
    shutil.copytree(args.python_base, python_target,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'Scripts'))
    shutil.copytree(args.python_environment/'Lib/site-packages', python_target/'Lib/site-packages',
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # Windows ._pth isolation prevents use of registry/global/user Python paths.
    (python_target/'python314._pth').write_text(
        '.\nLib\nDLLs\nLib/site-packages\n../\n../network\n../256mb system/src\n',
        encoding='utf-8', newline='\n')
    if args.original_game:
        for suffix in ('.bin', '.cue', '.lba', '.xml'):
            original = args.original_game.with_suffix(suffix)
            if original.is_file(): copy_verified(original, ROOT/'assets/original'/original.name)
    (ROOT/'LOCAL_RUNTIME.json').write_text(json.dumps(dict(runtime_files_verified=count,
        portable_python='.python/python.exe', game_assets='runtime/system256',
        origin_manifest_verified=True), indent=2), encoding='utf-8')
    print(f'Local runtime ready: {count} runtime files verified; standalone Python copied.')

if __name__ == '__main__': main()
