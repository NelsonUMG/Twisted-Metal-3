"""Deploy the lobby and CGNAT relay client, preserving configuration and saves."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import time
import zipfile
import importlib.metadata
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'network'))
from directory_defaults import PUBLIC_DIRECTORY_URL
from package_tm3_semiproduction import digest, source_zip

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist/TM3Online_UI2_175_20261021'
INSTALLED = ROOT / 'TM3Online_Lobby'
WORK = ROOT / 'diagnostics/session_rules_v3'

def main():
    public_verified = False
    if PUBLIC_DIRECTORY_URL:
        proof = json.loads((ROOT / 'diagnostics/rooms_auto_v1/public_installed.json').read_text())
        assert proof['passed'] and proof['real_cloudflare_deployment']
        assert proof['public_https_verified'] and proof['public_wss_verified']
        assert proof['endpoint'] == PUBLIC_DIRECTORY_URL
        assert proof['worker_source_sha256'] == digest(ROOT / 'network/cloudflare/src/worker.js')
        public_verified = True
    original = json.loads((DIST / 'BUILD_MANIFEST.json').read_text())
    for entry in original['files']:
        for folder in (DIST, INSTALLED):
            if folder == INSTALLED and entry['file'] == 'TM3Lobby.json':
                continue  # Personal server URL/runtime settings are user-owned.
            assert digest(folder / entry['file']) == entry['sha256'], entry['file']
    backup = ROOT / 'diagnostics/ice_p2p_v1/before'
    if not backup.exists():
        backup.mkdir(parents=True)
        for rel in ('TM3Lobby.exe', 'runtime/TM3Online.exe', 'BUILD_MANIFEST.json', 'sources/console.zip',
                    'sources/network/lobby_client.py', 'sources/network/lobby_server.py',
                    'sources/network/lobby_language.py', 'sources/network/lobby_entry.py',
                    'sources/update_ui2_session_release.py', 'TM3Lobby.json'):
            target = backup / rel; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(INSTALLED / rel, target)
    elif '--refresh' not in sys.argv:
        raise RuntimeError('Backup exists; use --refresh only for the same verified update')
    build = WORK / 'lobby_build'
    subprocess.run([str(ROOT / 'tools/.venv_lobby/Scripts/python.exe'), '-m', 'PyInstaller', '--noconfirm',
        '--onefile', '--windowed', '--name', 'TM3Lobby', '--distpath', str(build / 'dist'),
        '--workpath', str(build / 'work'), '--specpath', str(build), '--paths', str(ROOT / 'network'),
        str(ROOT / 'network/lobby_entry.py')], check=True)
    shutil.copy2(build / 'dist/TM3Lobby.exe', DIST / 'TM3Lobby.exe')
    shutil.copy2(ROOT / 'diagnostics/lobby_console_v1/build/Release/TM3Online.exe', DIST / 'runtime/TM3Online.exe')
    shutil.copy2(ROOT / 'network/UI2_README.md', DIST / 'LEEME.md')
    shutil.copy2(ROOT / 'docs/2PLUS2_EXPERIMENTAL_ES.md', DIST / '2PLUS2_ES.md')
    shutil.copy2(ROOT / 'docs/INTERNET_CGNAT_ES.md', DIST / 'INTERNET_CGNAT_ES.md')
    shutil.copy2(ROOT / 'docs/P2P_ICE_PRUEBA_ES.md', DIST / 'P2P_ICE_PRUEBA_ES.md')
    shutil.copy2(ROOT / 'docs/ACTUALIZAR_P2P_ES.md', DIST / 'ACTUALIZAR_P2P_ES.md')
    shutil.copy2(ROOT / 'docs/SIMULACION_NAT_ES.md', DIST / 'SIMULACION_NAT_ES.md')
    shutil.copy2(ROOT / 'docs/SALAS_AUTOMATICAS_ES.md', DIST / 'SALAS_AUTOMATICAS_ES.md')
    source_zip(ROOT / 'diagnostics/lobby_console_v1/frontend', DIST / 'sources/console.zip')
    for name in ('lobby_client.py', 'lobby_server.py', 'lobby_entry.py', 'lobby_language.py',
                 'relay_protocol.py', 'relay_client.py', 'relay_server.py', 'Dockerfile.lobby',
                 'p2p_codes.py', 'p2p_session.py', 'p2p_game.py', 'p2p_window.py', 'p2p_probe.py',
                 'worker_directory.py', 'directory_defaults.py', 'rooms_probe.py', 'test_auto_rooms.py',
                 'requirements-p2p.txt', 'test_p2p.py',
                 'test_relay.py', 'test_lobby.py', 'test_lobby_client.py', 'test_lobby_chat.py'):
        shutil.copy2(ROOT / 'network' / name, DIST / 'sources/network' / name)
    notices = []
    for dependency in ('aiortc', 'aioice', 'av', 'cryptography', 'google-crc32c', 'pyee', 'pylibsrtp',
                       'pyOpenSSL', 'dnspython', 'ifaddr', 'cffi', 'pycparser', 'typing_extensions', 'websockets'):
        distribution = importlib.metadata.distribution(dependency)
        notices.append(dict(package=dependency, version=distribution.version,
            license=distribution.metadata.get('License-Expression') or distribution.metadata.get('License', ''),
            project_urls=distribution.metadata.get_all('Project-URL') or []))
        for item in distribution.files or []:
            if '/licenses/' in str(item).replace('\\', '/') and item.suffix not in ('.py', '.pyc'):
                destination = DIST / 'licenses/p2p' / dependency / Path(*item.parts[2:])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(item), destination)
    (DIST / 'licenses/P2P_DEPENDENCIES.json').write_text(json.dumps(notices, indent=2), encoding='utf-8')
    shutil.copytree(ROOT / 'network/deploy', DIST / 'sources/network/deploy', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('.env'))
    shutil.copytree(ROOT / 'network/cloudflare', DIST / 'sources/network/cloudflare', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('node_modules', '.wrangler', '.env', '.dev.vars'))
    shutil.copy2(Path(__file__), DIST / 'sources/update_ui2_session_release.py')
    original['session_update'] = dict(version='session_rules_v3', protocol=7, directory_version=2,
        host_game_role=2, guest_game_role=1, startup_requires_guest_connection_flag=True,
        cancel_returns_both=True, directory_owned_by_gui=True, game_parent_lifetime=True,
        validation='53 Python tests, 12 CTest tests, two actual linked game boots, guest cancel and graceful exits')
    original['triangle_cancel_update'] = dict(version='triangle_cancel_v4', triangle_intent_required=True,
        normal_level_transition_does_not_cancel=True, native_menu_return_keeps_transport=True)
    original['local_players_update'] = dict(version='dual_port_v5', date='2026-10-22', experimental=True,
        local_controller_ports=2, second_player_default_enabled=False, shared_physical_controller=False,
        target_human_players=4, four_human_race_validated=False,
        validation='Independent controller allocation, per-port binding persistence, 60-byte 2+2 batch, two actual emulators with port 2 enabled')
    original['internet_update'] = dict(version='internet_relay_v1', date='2026-10-22',
        relay_protocol=1, game_protocol=7, tls_required_for_internet=True,
        public_server_configured=False, cross_isp_validated=False, cgnat_real_network_validated=False,
        local_https_gateway_validated=True, protocol_bridge_validated=True,
        direct_ice_implemented=False, udp_relay_fast_path=False,
        transport='TCP control and UDP gameplay framed over HTTPS Upgrade / TLS',
        validation='70 Python tests; C++ relay: 64 KiB + 300 x 60-byte exchanges with packet loss; actual dual-port emulator boot and cancellation')
    original['p2p_update'] = dict(version='ice_p2p_v1', date='2026-10-22', experimental=True,
        engine='aiortc 1.15.0 / aioice 0.10.2', manual_offer_answer=False,
        manual_ui_removed=True,
        direct_ice_implemented=True, dtls_encryption=True, reliable_control=True,
        unordered_unreliable_gameplay=True, default_stun='stun:stun.cloudflare.com:3478',
        game_flow_control='bounded_retry_coalescing_v1', simulated_double_nat_tested=True,
        invitation_lifetime_seconds=1800, invitation_expiry_clock='monotonic_local',
        delayed_manual_answer_supported=True,
        simulated_high_latency_loss_repetitions=3,
        stun_public_candidate_observed=True, own_public_server_required=False,
        cross_isp_validated=False, mobile_hotspot_validated=False, four_human_race_validated=False,
        validation='84 Python tests + 8 NAT-model tests; clock-offset and monotonic-expiry checks; simulated NAT/loss/latency; real GUI and two emulators')
    original['automatic_rooms_update'] = dict(version='automatic_rooms_v1', date='2026-10-22',
        manual_codes=False, shared_directory='Cloudflare Workers + SQLite Durable Objects',
        websocket_rpc=True, transient_room_state=True, gameplay_on_player_pcs=True,
        public_directory_configured=bool(PUBLIC_DIRECTORY_URL), public_directory_url=PUBLIC_DIRECTORY_URL,
        cloudflare_public_deployment_verified=public_verified,
        real_wan_validated=False, real_mobile_network_validated=False, turn_service_provisioned=False,
        validation='99 Python tests; 7 Worker runtime tests; 3 real lobby UIs + two emulators over simulated NAT; automatic create/join/start/cancel/restart; public HTTPS/WSS frozen-client signaling')
    original['latency_update'] = dict(version='peer_rtt_v1', date='2026-10-22',
        measurement='application round-trip time over the encrypted peer control channel',
        excludes_directory_round_trip=True, excludes_emulator_input_to_display_delay=True,
        probe_interval_seconds=2, sample_window=30, stale_after_seconds=6,
        latest_average_and_mean_absolute_rtt_variation=True,
        matched_monotonic_probes_only=True, bounded_history=True,
        visible_in_room_and_lobby=True, compatible_with_previous_peer_ping=True,
        real_player_rtt_not_measured_by_local_qa=True)
    original['files'] = [dict(file=str(p.relative_to(DIST)), bytes=p.stat().st_size, sha256=digest(p))
        for p in sorted(DIST.rglob('*')) if p.is_file() and p.name != 'BUILD_MANIFEST.json']
    (DIST / 'BUILD_MANIFEST.json').write_text(json.dumps(original, indent=2), encoding='utf-8')
    for path in DIST.rglob('*'):
        if not path.is_file(): continue
        rel = path.relative_to(DIST)
        target = INSTALLED / rel
        if rel.as_posix() == 'TM3Lobby.json' and target.exists():
            continue
        if not target.exists() or digest(target) != digest(path):
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(path, target)
            except PermissionError:
                # Preserve the running executable without interrupting the user's
                # current session. Windows allows its image to be renamed.
                running_backup = ROOT / 'diagnostics/triangle_cancel_v4/running_previous' / rel
                running_backup = running_backup.with_name(str(time.time_ns()) + '_' + running_backup.name)
                running_backup.parent.mkdir(parents=True, exist_ok=True)
                target.rename(running_backup)
                shutil.copy2(path, target)
    temporary = DIST.with_suffix('.session-update.zip')
    with zipfile.ZipFile(temporary, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(DIST.rglob('*')):
            if path.is_file(): archive.write(path, (Path(DIST.name) / path.relative_to(DIST)).as_posix())
    with zipfile.ZipFile(temporary) as archive:
        assert archive.testzip() is None
    temporary.replace(DIST.with_suffix('.zip'))
    shutil.copy2(DIST.with_suffix('.zip'), ROOT / 'TM3Online_Portatil.zip')
    assert digest(ROOT / 'TM3Online_Portatil.zip') == digest(DIST.with_suffix('.zip'))
    server_bundle = ROOT / 'TM3Online_Servidor_Internet.zip'
    with zipfile.ZipFile(server_bundle, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(ROOT / 'docs/INTERNET_CGNAT_ES.md', 'INTERNET_CGNAT_ES.md')
        for path in sorted((DIST / 'sources/network').rglob('*')):
            if path.is_file() and path.name != '.env':
                archive.write(path, (Path('network') / path.relative_to(DIST / 'sources/network')).as_posix())
    with zipfile.ZipFile(server_bundle) as archive:
        assert archive.testzip() is None
    patch_bundle = ROOT / 'TM3Online_Actualizacion_P2P.zip'
    with zipfile.ZipFile(patch_bundle, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in ('TM3Lobby.exe', 'SALAS_AUTOMATICAS_ES.md', 'ACTUALIZAR_P2P_ES.md', 'licenses/P2P_DEPENDENCIES.json'):
            archive.write(DIST / name, name)
        for path in sorted((DIST / 'licenses/p2p').rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(DIST).as_posix())
    with zipfile.ZipFile(patch_bundle) as archive:
        assert archive.testzip() is None
    shutil.copy2(patch_bundle, ROOT / 'TM3Online_Actualizacion_Salas.zip')
    cloudflare_bundle = ROOT / 'TM3Online_Directorio_Cloudflare.zip'
    with zipfile.ZipFile(cloudflare_bundle, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted((DIST / 'sources/network/cloudflare').rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(DIST / 'sources/network').as_posix())
        archive.write(ROOT / 'docs/SALAS_AUTOMATICAS_ES.md', 'SALAS_AUTOMATICAS_ES.md')
    with zipfile.ZipFile(cloudflare_bundle) as archive:
        assert archive.testzip() is None
    print(json.dumps(dict(installed=True, portable=str(ROOT / 'TM3Online_Portatil.zip'),
                          sha256=digest(ROOT / 'TM3Online_Portatil.zip')), indent=2))

if __name__ == '__main__': main()
