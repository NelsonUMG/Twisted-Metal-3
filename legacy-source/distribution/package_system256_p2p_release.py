"""Publish the one-console-per-PC P2P runtime into the portable ZIP.

The original archive is backed up before any replacement. The archive is
rewritten as a temporary file and only atomically replaces the release after
all entries, hashes, and ZIP integrity have been checked.
"""
from pathlib import Path
import copy
import hashlib
import json
import os
import shutil
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / 'TM3Online_Portatil.zip'
BACKUP = ROOT / 'TM3Online_Portatil_ANTES_P2P_CABLE_20261022.zip'
PREFIX = 'TM3Online_UI2_175_20261021/'
FROZEN_EXE = ROOT / 'diagnostics/system256_cable_p2p_qa/frozen/dist/TM3Lobby_P2P.exe'

DOC = '''# SYSTEM256 — salas en línea P2P

1. Extrae la carpeta completa en ambas PC y abre TM3Lobby.exe.
2. Entra a la misma sala; el anfitrión pulsa START cuando ambos estén listos.
3. Cada PC ejecuta una sola consola visible. No se inicia una réplica oculta.
4. Esc cierra el juego y vuelve al lobby; F11 alterna pantalla completa.

El lobby usa Cloudflare Workers para publicar salas y coordinar la señalización.
ICE/STUN intenta negociar una ruta directa entre las dos PC; el tráfico de la
partida no pasa por Cloudflare. Los mensajes del cable SYSTEM256 viajan por el
canal P2P cifrado y fiable. RTT muestra el tiempo de ida y vuelta del canal de
control, no mide por sí solo el retardo del mando hasta la pantalla.

No se agrega una espera artificial de entrada ni un prebúfer fijo de audio de
80 ms. Cada PC genera y reproduce localmente el audio de su propia consola.
La imagen inicia en 1× y conserva la proporción 4:3. Vulkan se detecta por PC;
si falla en cualquiera de los dos extremos, ambos usan Software.

La ruta probada es conexión directa. Este paquete no incluye TURN/relay de
juego: algunas redes con CGNAT o firewalls restrictivos no permiten P2P directo
y todavía pueden requerir un relay público. La prueba incluida abajo no
certifica conectividad entre proveedores o países distintos.
'''


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    if not ARCHIVE.is_file() or not zipfile.is_zipfile(ARCHIVE):
        raise FileNotFoundError(f'Portable ZIP not found: {ARCHIVE}')
    if not FROZEN_EXE.is_file() or FROZEN_EXE.stat().st_size < 5_000_000:
        raise FileNotFoundError(f'Validated frozen executable not found: {FROZEN_EXE}')

    with zipfile.ZipFile(ARCHIVE, 'r') as old:
        bad = old.testzip()
        if bad:
            raise RuntimeError(f'Existing ZIP failed integrity check at {bad}')
        old_names = set(old.namelist())
        required_before = {
            PREFIX + 'TM3Lobby.exe',
            PREFIX + 'TM3Lobby.json',
            PREFIX + 'runtime/TM3Console.ini',
            PREFIX + 'runtime/system256/TM3_SYSTEM256.bin',
            PREFIX + 'runtime/system256/TM3_SYSTEM256.cue',
            PREFIX + 'runtime/system256/beetle_psx_system256.dll',
        }
        missing = required_before - old_names
        if missing:
            raise RuntimeError(f'Portable package is incomplete: {sorted(missing)}')
        config = json.loads(old.read(PREFIX + 'TM3Lobby.json').decode('utf-8-sig'))
        settings = old.read(PREFIX + 'runtime/TM3Console.ini').decode('utf-8-sig')
        manifest = json.loads(old.read(PREFIX + 'BUILD_MANIFEST.json').decode('utf-8-sig'))

    # Preserve the exact pre-update ZIP as a recoverable backup. If an earlier
    # interrupted attempt left the same backup, allow a safe retry only while
    # the source archive is still byte-for-byte identical.
    if BACKUP.exists():
        if BACKUP.stat().st_size != ARCHIVE.stat().st_size or digest(BACKUP) != digest(ARCHIVE):
            raise FileExistsError(f'Backup exists but does not match the current source ZIP: {BACKUP}')
    else:
        shutil.copy2(ARCHIVE, BACKUP)

    config.setdefault('system256', {})
    config['system256'].update({
        'enabled': True,
        'assets': 'runtime/system256',
        'protocol': 'SYSTEM256-CABLE-P2P1',
        'local_consoles_per_pc': 1,
        'gameplay_transport': 'encrypted_reliable_webrtc_data_channel',
        'cloudflare_game_relay': False,
    })
    config['system256'].pop('input_delay_policy', None)
    config['system256'].pop('initial_delay_frames', None)
    config['runtime']['variant'] = 'SYSTEM256 ABI6 + P2P cable + one console per PC + CPU175'

    settings_lines = [line for line in settings.splitlines()
                      if not line.startswith('AudioLatency=')]
    settings = '\n'.join(settings_lines) + '\n'

    replacements = {
        'TM3Lobby.exe': FROZEN_EXE,
        'TM3Lobby.json': None,
        'SYSTEM256_PRUEBA_ES.md': None,
        'runtime/TM3Console.ini': None,
        'sources/network/system256_runtime.py': ROOT / 'network/system256_runtime.py',
        'sources/network/system256_bridge.py': ROOT / 'network/system256_bridge.py',
        'sources/network/system256_peer_cable.py': ROOT / 'network/system256_peer_cable.py',
        'sources/network/test_system256_bridge.py': ROOT / 'network/test_system256_bridge.py',
        'sources/network/test_system256_peer_cable.py': ROOT / 'network/test_system256_peer_cable.py',
        'sources/network/lobby_client.py': ROOT / 'network/lobby_client.py',
        'sources/network/lobby_entry.py': ROOT / 'network/lobby_entry.py',
        'sources/system256/twin_core.py': ROOT / '256mb system/src/twin_core.py',
    }
    deleted = {
        PREFIX + 'sources/system256/input_stream.py',
        PREFIX + 'sources/system256/demand_feed.py',
    }

    with tempfile.TemporaryDirectory(prefix='tm3_p2p_release_') as temporary:
        temporary = Path(temporary)
        config_path = temporary / 'TM3Lobby.json'
        config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
        doc_path = temporary / 'SYSTEM256_PRUEBA_ES.md'
        doc_path.write_text(DOC, encoding='utf-8')
        settings_path = temporary / 'TM3Console.ini'
        settings_path.write_text(settings, encoding='utf-8')
        replacements['TM3Lobby.json'] = config_path
        replacements['SYSTEM256_PRUEBA_ES.md'] = doc_path
        replacements['runtime/TM3Console.ini'] = settings_path

        # Regenerate the manifest records for replaced/new files and remove
        # obsolete input-stream engine files from its inventory.
        replacement_hashes = {}
        for relative, source in replacements.items():
            package_relative = relative.replace('/', '\\')
            replacement_hashes[package_relative] = dict(
                file=package_relative,
                bytes=source.stat().st_size,
                sha256=digest(source),
            )
        for relative in ('sources/network/system256_runtime.py',
                         'sources/network/system256_bridge.py',
                         'sources/network/system256_peer_cable.py',
                         'sources/network/test_system256_bridge.py',
                         'sources/network/test_system256_peer_cable.py',
                         'sources/network/lobby_client.py', 'sources/network/lobby_entry.py',
                         'sources/system256/twin_core.py'):
            package_relative = relative.replace('/', '\\')
            replacement_hashes[package_relative] = dict(
                file=package_relative, bytes=replacements[relative].stat().st_size,
                sha256=digest(replacements[relative]))
        deleted_relative = {name[len(PREFIX):].replace('/', '\\') for name in deleted}
        file_records = {entry['file']: entry for entry in manifest.get('files', [])
                        if entry.get('file') not in deleted_relative}
        file_records.update(replacement_hashes)
        manifest['files'] = [file_records[name] for name in sorted(file_records)]
        manifest['date'] = '2026-10-22'
        manifest['validation'] = (
            '96 Python regression tests; production-frozen executable tested with two real '
            'ICE/DTLS/SCTP peers on one PC for 600 gameplay ticks; one core per process; '
            '764 cable exchanges; zero TIME/RNG mismatches; approximately 29.9 ticks/s. '
            'ICE selected host-host candidates (local path); test audio used SDL dummy and '
            'Vulkan rendered offscreen. One peer observed a single cable wait near 2.0 s. '
            'No cross-ISP, mobile-hotspot, audible-output, visible-presentation, or hard-CGNAT certification.'
        )
        manifest['system256_p2p_cable'] = dict(
            protocol='SYSTEM256-CABLE-P2P1',
            local_consoles_per_pc=1,
            gameplay_payload='encrypted reliable WebRTC DataChannel, direct peer-to-peer',
            cloudflare_game_relay=False,
            artificial_input_delay=False,
            audio='independent local output on each PC',
            external_wan_validated=False,
            full_gameplay_ticks_per_peer=600,
            cable_exchanges_per_peer=764,
            time_mismatches_per_peer=0,
            rng_mismatches_per_peer=0,
            local_same_pc_selected_candidates='host-host',
            local_same_pc_rtt_average_ms=1.714,
            cable_wait_mean_ms_per_peer=[0.419, 16.279],
            cable_wait_max_ms_per_peer=[47.51, 2002.899],
            gameplay_rate_ticks_per_second_per_peer=[29.971, 29.896],
            audio_qa_backend='SDL dummy (audio generation/startup checked; not audible)',
            video_qa_backend='Vulkan offscreen (rendered frames checked; not visible presentation)',
        )
        manifest_path = temporary / 'BUILD_MANIFEST.json'
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        replacements['BUILD_MANIFEST.json'] = manifest_path

        handle, temp_name = tempfile.mkstemp(prefix='TM3Online_Portatil_P2P_',
            suffix='.tmp.zip', dir=ROOT)
        os.close(handle)
        temporary_zip = Path(temp_name)
        try:
            written = set()
            with zipfile.ZipFile(ARCHIVE, 'r') as old, zipfile.ZipFile(
                    temporary_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as new:
                for info in old.infolist():
                    name = info.filename
                    relative = name[len(PREFIX):] if name.startswith(PREFIX) else ''
                    if name in deleted:
                        continue
                    if relative in replacements:
                        new.write(replacements[relative], name)
                        written.add(relative)
                    elif name.endswith('/'):
                        new.writestr(info, b'')
                    else:
                        copied = copy.copy(info)
                        with old.open(info, 'r') as source, new.open(copied, 'w') as target:
                            shutil.copyfileobj(source, target, length=1024 * 1024)
                for relative, source in replacements.items():
                    if relative not in written:
                        new.write(source, PREFIX + relative)

            with zipfile.ZipFile(temporary_zip, 'r') as check:
                names = check.namelist()
                if len(names) != len(set(names)):
                    raise RuntimeError('Updated ZIP contains duplicate entries')
                bad = check.testzip()
                if bad:
                    raise RuntimeError(f'Updated ZIP failed integrity check at {bad}')
                check_config = json.loads(check.read(PREFIX + 'TM3Lobby.json'))
                check_doc = check.read(PREFIX + 'SYSTEM256_PRUEBA_ES.md').decode('utf-8')
                check_manifest = json.loads(check.read(PREFIX + 'BUILD_MANIFEST.json'))
                if check.read(PREFIX + 'TM3Lobby.exe') != FROZEN_EXE.read_bytes():
                    raise RuntimeError('Packaged executable hash/content mismatch')
                if check_config['system256'].get('local_consoles_per_pc') != 1:
                    raise RuntimeError('Package does not declare one console per PC')
                if check_config['system256'].get('input_delay_policy'):
                    raise RuntimeError('Stale artificial input-delay setting remains')
                if 'una sola consola visible' not in check_doc or 'TURN/relay' not in check_doc:
                    raise RuntimeError('P2P architecture or CGNAT caveat missing from guide')
                if PREFIX + 'sources/network/system256_peer_cable.py' not in names:
                    raise RuntimeError('P2P cable source missing from package')
                if any(name in names for name in deleted):
                    raise RuntimeError('Obsolete hidden-engine source remains in package')
                if check_manifest.get('system256_p2p_cable', {}).get('local_consoles_per_pc') != 1:
                    raise RuntimeError('Manifest does not declare one core per PC')
                recorded = {entry['file']: entry for entry in check_manifest.get('files', [])}
                for relative in replacements:
                    if relative == 'BUILD_MANIFEST.json':
                        continue
                    package_relative = relative.replace('/', '\\')
                    entry = recorded.get(package_relative)
                    content = check.read(PREFIX + relative)
                    if not entry or entry.get('bytes') != len(content) or entry.get('sha256') != hashlib.sha256(content).hexdigest():
                        raise RuntimeError(f'Build manifest checksum mismatch: {relative}')

            # Atomic swap: the existing ZIP remains intact until every check passes.
            temporary_zip.replace(ARCHIVE)
            print(json.dumps(dict(archive=str(ARCHIVE), backup=str(BACKUP),
                bytes=ARCHIVE.stat().st_size, files=len(names),
                exe_sha256=digest(FROZEN_EXE), zip_integrity=True,
                one_console_per_pc=True, p2p_cable_protocol='SYSTEM256-CABLE-P2P1',
                external_wan_validated=False), indent=2, ensure_ascii=False))
        finally:
            if temporary_zip.exists():
                temporary_zip.unlink()


if __name__ == '__main__':
    main()
