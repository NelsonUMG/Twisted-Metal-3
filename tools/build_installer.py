"""Build an installer from a frozen lobby and a tested runtime directory.

Game images/BIOS/saves and user settings are never bundled in public releases.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--iscc', type=Path)
    parser.add_argument('--stage-only', action='store_true', help='Prepare and verify payload without running Inno Setup')
    parser.add_argument('--skip-freeze', action='store_true')
    args = parser.parse_args()
    payload = ROOT/'build/payload'; payload.mkdir(parents=True, exist_ok=True)
    if not args.skip_freeze:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
            '--distpath', str(payload), '--workpath', str(ROOT/'build/pyinstaller'),
            str(ROOT/'installer/lobby.spec')], cwd=ROOT, check=True)
    if not (payload/'TM3Lobby.exe').is_file(): raise FileNotFoundError('Frozen lobby missing')
    # Explicit allowlist prevents accidental distribution of game/user data.
    names = ('system256/beetle_psx_system256.dll', 'system256/beetle_psx_system256_vulkan.dll',
             'system256/tm3_vulkan_frontend.dll', 'system256/libwinpthread-1.dll',
             'TM3Online.exe', 'cores/beetle_psx_libretro.dll')
    for name in names:
        source = args.runtime/name
        if not source.is_file(): raise FileNotFoundError(source)
        dest = payload/'runtime'/name; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    for source, name in ((ROOT/'VERSION', 'VERSION'), (ROOT/'config/TM3Lobby.json', 'TM3Lobby.json')):
        shutil.copy2(source, payload/name)
    # Retain expected game hashes, but ship only DLLs and configuration.
    original_manifest = args.runtime.parent/'RELEASE_FILES.json'
    expected = json.loads(original_manifest.read_text(encoding='utf-8'))
    for name in expected['system256']:
        source = args.runtime/'system256'/name
        if source.suffix == '.dll':
            with source.open('rb') as stream: expected['system256'][name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    (payload/'RELEASE_FILES.json').write_text(json.dumps(expected, indent=2), encoding='utf-8')
    license_dir = args.runtime.parent/'licenses'
    if license_dir.is_dir(): shutil.copytree(license_dir, payload/'licenses', dirs_exist_ok=True)
    for path in payload.rglob('*'):
        if path.suffix.lower() in ('.bin', '.cue', '.iso', '.rom'):
            raise ValueError('Unexpected game/BIOS file in payload: ' + str(path))
    version = (ROOT/'VERSION').read_text().strip()
    if args.stage_only:
        print(json.dumps(dict(payload=str(payload), version=version, game_images_included=False)))
        return
    if not args.iscc or not args.iscc.is_file():
        raise FileNotFoundError('Install Inno Setup and supply --iscc path/to/ISCC.exe')
    subprocess.run([str(args.iscc.resolve()), f'/DAppVersion={version}',
        f'/DPayloadDir={payload}', str(ROOT/'installer/TM3Online.iss')], check=True)
    exe = ROOT/'dist/TM3Online-Setup.exe'
    with exe.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (ROOT/'dist/SHA256SUMS.txt').write_text(f'{digest}  {exe.name}\n', encoding='ascii')
    print(json.dumps(dict(installer=str(exe), sha256=digest)))

if __name__ == '__main__': main()
