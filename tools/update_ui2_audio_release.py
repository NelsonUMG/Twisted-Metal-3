"""Deploy the verified audio-reserve fix and refresh the existing portable ZIP."""
from pathlib import Path
import json
import shutil
import zipfile
from package_tm3_semiproduction import digest, source_zip

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist/TM3Online_UI2_175_20261021'
INSTALLED = ROOT / 'TM3Online_Lobby'
BACKUP = ROOT / 'diagnostics/audio_reserve_v1/before'

def main():
    original = json.loads((DIST / 'BUILD_MANIFEST.json').read_text())
    for entry in original['files']:
        for folder in (DIST, INSTALLED):
            assert digest(folder / entry['file']) == entry['sha256'], entry['file']
    shutil.copy2(DIST / 'BUILD_MANIFEST.json', BACKUP / 'BUILD_MANIFEST.json')
    shutil.copy2(DIST / 'sources/console.zip', BACKUP / 'console.zip')
    source_zip(ROOT / 'diagnostics/lobby_console_v1/frontend', DIST / 'sources/console.zip')
    shutil.copy2(ROOT / 'diagnostics/lobby_console_v1/build/Release/TM3Online.exe', DIST / 'runtime/TM3Online.exe')
    shutil.copy2(ROOT / 'network/UI2_README.md', DIST / 'LEEME.md')
    original['audio_update'] = dict(version='reserve_v1', default_capacity_ms=80,
        startup_reserve_ms=40, nonblocking_refill=True, time_stretch=False,
        validation='12 CTest tests including WaveOut reserve/refill; real gameplay listening still required')
    original['files'] = [dict(file=str(p.relative_to(DIST)), bytes=p.stat().st_size, sha256=digest(p))
        for p in sorted(DIST.rglob('*')) if p.is_file() and p.name != 'BUILD_MANIFEST.json']
    (DIST / 'BUILD_MANIFEST.json').write_text(json.dumps(original, indent=2), encoding='utf-8')
    for relative in ('runtime/TM3Online.exe', 'sources/console.zip', 'LEEME.md', 'BUILD_MANIFEST.json'):
        shutil.copy2(DIST / relative, INSTALLED / relative)
    archive_path = DIST.with_suffix('.zip')
    temporary = DIST.with_suffix('.audio-update.zip')
    with zipfile.ZipFile(temporary, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(DIST.rglob('*')):
            if path.is_file(): archive.write(path, (Path(DIST.name) / path.relative_to(DIST)).as_posix())
    with zipfile.ZipFile(temporary) as archive:
        assert archive.testzip() is None
    temporary.replace(archive_path)
    for entry in original['files']:
        assert digest(INSTALLED / entry['file']) == entry['sha256']
    print(json.dumps(dict(installed=True, zip=str(archive_path), sha256=digest(archive_path),
                         saves_and_preferences_untouched=True), indent=2))

if __name__ == '__main__':
    main()
