"""Build UI2 clean release without touching installed saves or personal settings."""
from pathlib import Path
import json
import shutil
import subprocess
import zipfile
from package_tm3_semiproduction import digest, source_zip

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / 'diagnostics/console_v2'
DIST = ROOT / 'dist/TM3Online_UI2_175_20261021'
PACKAGE = ROOT / 'TM3Online_Lobby'

def main():
    if DIST.exists():
        raise RuntimeError('Release already exists; refusing overwrite')
    build = WORK / 'lobby_build'
    subprocess.run([str(ROOT / 'tools/.venv_lobby/Scripts/python.exe'), '-m', 'PyInstaller',
        '--noconfirm', '--onefile', '--windowed', '--name', 'TM3Lobby', '--distpath', str(build / 'dist'),
        '--workpath', str(build / 'work'), '--specpath', str(build), '--paths', str(ROOT / 'network'),
        str(ROOT / 'network/lobby_entry.py')], check=True)
    DIST.mkdir(parents=True)
    def copy(source, relative):
        target = DIST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    copy(build / 'dist/TM3Lobby.exe', 'TM3Lobby.exe')
    copy(ROOT / 'network/lobby_portable_config.json', 'TM3Lobby.json')
    copy(ROOT / 'network/UI2_README.md', 'LEEME.md')
    copy(ROOT / 'diagnostics/lobby_console_v1/build/Release/TM3Online.exe', 'runtime/TM3Online.exe')
    copy(ROOT / 'diagnostics/semiproduction175/core/beetle_psx_ui2.dll', 'runtime/cores/beetle_psx_libretro.dll')
    for name in ('TM3_SQRT_MERGE_V4.bin', 'TM3_SQRT_MERGE_V4.cue'):
        copy(PACKAGE / 'runtime/game' / name, 'runtime/game/' + name)
    assert digest(DIST / 'runtime/game/TM3_SQRT_MERGE_V4.bin') == 'EBAF1EAA5D43DDFD3C88A860F0205482DEDE4EE20AEBE5555B2D65B0A1BFF14C'
    shutil.copytree(PACKAGE / 'runtime/system', DIST / 'runtime/system')
    for path in (PACKAGE / 'runtime').glob('*.dll'):
        copy(path, 'runtime/' + path.name)
    shutil.copytree(PACKAGE / 'licenses', DIST / 'licenses')
    (DIST / 'sources').mkdir()
    source_zip(ROOT / 'diagnostics/semiproduction175/core', DIST / 'sources/core_cpu175.zip')
    source_zip(ROOT / 'diagnostics/lobby_console_v1/frontend', DIST / 'sources/console.zip')
    for name in ('lobby_client.py', 'lobby_language.py', 'lobby_server.py', 'lobby_entry.py', 'lobby_portable_config.json'):
        copy(ROOT / 'network' / name, 'sources/network/' + name)
    for name in ('package_tm3_ui2.py', 'package_tm3_semiproduction.py'):
        copy(ROOT / 'tools' / name, 'sources/' + name)
    records = [dict(file=str(p.relative_to(DIST)), bytes=p.stat().st_size, sha256=digest(p))
               for p in sorted(DIST.rglob('*')) if p.is_file()]
    manifest = dict(format='TM3_UI2_175_V2', date='2026-10-21', cpu_budget_percent=175,
        other_ps1_cpu_budget_percent=100, default_language='en', supported_languages=['en', 'es'],
        diagnostics_enabled=False, game_disc_unchanged=True,
        validation='12 CTest tests, 49 Python tests, real core repeated load/unload; long online gameplay not validated', files=records)
    (DIST / 'BUILD_MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    archive_path = DIST.with_suffix('.zip')
    with zipfile.ZipFile(archive_path, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(DIST.rglob('*')):
            if path.is_file():
                archive.write(path, (Path(DIST.name) / path.relative_to(DIST)).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
    print(json.dumps(dict(distribution=str(DIST), zip=str(archive_path), zip_sha256=digest(archive_path)), indent=2))

if __name__ == '__main__':
    main()
