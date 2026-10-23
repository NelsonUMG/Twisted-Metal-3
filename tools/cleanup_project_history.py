"""Explicit, audited retirement of pre-UI2 launchers and distribution artifacts."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs/cleanup_final_20261021'

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def safe(path):
    assert path.resolve(strict=True).is_relative_to(ROOT) and path.resolve() != ROOT
    assert not path.is_symlink() and not path.is_junction(), path
    return path

def main():
    active = ROOT / 'TM3Online_Lobby'
    release = ROOT / 'dist/TM3Online_UI2_175_20261021'
    manifest = json.loads((release / 'BUILD_MANIFEST.json').read_text())
    for row in manifest['files']:
        assert digest(active / row['file']).upper() == row['sha256']
        assert digest(release / row['file']).upper() == row['sha256']
    OUT.mkdir(exist_ok=False)
    files = []
    for pattern in ('TM3_*.cmd', 'REPORTE_PARA_CLAUDE*.md', 'RESPUESTA_PARA_CLAUDE*.md',
                    'RESUMEN_PARA_CLAUDE*.md', 'mkpsxiso_rngcaller_v12.*.log'):
        files.extend(ROOT.glob(pattern))
    for name in ('DIAGNOSTICO_RNGTRACE_20260728.md', 'RESTAURACION_V10_20260728.md',
                 'SHA256_FRONTEND_V11.txt', 'SHA256_SCUS_MODIFICADO.txt', 'TM3_ONLINE_v10.lba',
                 '.codex_tmp_v9_ips_verify', 'COMO_EJECUTAR.txt', 'LEEME_PRIMERO.txt', 'README_ES.md',
                 'EJECUTAR_TM3_RECOMP.cmd', 'EJECUTAR_TM3ONLINE_SIN_BIOS.bat',
                 'INSTALAR_CORE_BEETLE_PSX.bat', 'PROBAR_2_CONSOLAS_LOCAL.bat',
                 'PROBAR_2_CONSOLAS_LOCAL_V11.bat', 'frontend.rar',
                 'TM3Online_Claude_Auditoria_Sincronizacion_v10_20260722.rar',
                 'TM3Online_Claude_Evidencia_Dinamica_8Vehiculos_20260728.rar',
                 'dist/TM3Online_SemiProduccion_175_20261021.zip'):
        path = ROOT / name
        if path.exists(): files.append(path)
    folders = [ROOT / name for name in (
        'Distribucion_Internet_v10', 'BACKUP_PRE_RESTORE_V11_20260728_0808',
        'ENTREGA_CLAUDE_EVIDENCIA_DINAMICA_20260728', 'ENTREGA_CLAUDE_SYNC_V10_20260722',
        '.video_analysis', 'dist/TM3Online_SemiProduccion_175_20261021',
        'TM3_RECOMP_PADDED_TEST/build-mingw') if (ROOT / name).exists()]
    for folder in folders:
        safe(folder)
        for path in folder.rglob('*'):
            safe(path)
            if path.is_file(): files.append(path)
    files = sorted(set(files))
    old = json.loads((ROOT / 'docs/cleanup_20261021/manifest.json').read_text())
    recoveries = {row['sha256']: row['recovery'] for row in old['removed']}
    records = []
    backup = OUT / 'historical_sources_and_reports.zip'
    with zipfile.ZipFile(backup, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            safe(path)
            rel = path.relative_to(ROOT).as_posix()
            sha = digest(path)
            # Preserve small historical sources/configs/reports, not multi-GB old packages.
            if path.stat().st_size < 100 * 1024 * 1024 and 'build-mingw' not in path.parts:
                archive.write(path, rel)
                recovery = backup.name
            elif sha in recoveries:
                recovery = recoveries[sha]
            elif sha.upper() == next(r['sha256'] for r in manifest['files'] if r['file'].endswith('.bin')):
                recovery = 'Identical active game: TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin'
            else:
                recovery = 'None: obsolete distribution archive or rebuildable compiled artifact'
            records.append(dict(path=rel, bytes=path.stat().st_size, sha256=sha, recovery=recovery))
    with zipfile.ZipFile(backup) as archive:
        assert archive.testzip() is None
        for row in records:
            if row['recovery'] == backup.name:
                assert hashlib.sha256(archive.read(row['path'])).hexdigest() == row['sha256']
    report = dict(status='validated_before_deletion', removed=records,
                  bytes_removed=sum(r['bytes'] for r in records), backup_bytes=backup.stat().st_size)
    report['net_bytes_freed'] = report['bytes_removed'] - report['backup_bytes']
    log = OUT / 'manifest.json'
    log.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for path in files:
        safe(path).unlink()
    for folder in folders:
        for path in sorted(folder.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            safe(path).rmdir()
        safe(folder).rmdir()
    for row in manifest['files']:
        assert digest(active / row['file']).upper() == row['sha256']
    report['status'] = 'completed_active_package_verified'
    log.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(files_removed=len(records), folders_removed=len(folders),
        bytes_freed=report['net_bytes_freed'], backup_bytes=report['backup_bytes'],
        active_package_verified=True), indent=2), flush=True)

if __name__ == '__main__':
    main()
