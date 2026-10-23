"""Audit automatic-room deliverables, deployment evidence, and preservation."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / 'diagnostics/rooms_auto_v1'
PREFIX = 'TM3Online_UI2_175_20261021/'
sys.path.insert(0, str(ROOT / 'network'))
from directory_defaults import PUBLIC_DIRECTORY_URL


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest().upper()


def main():
    before = json.loads((QA / 'before/BUILD_MANIFEST.json').read_text())
    for entry in before['files']:
        if entry['file'].replace('\\', '/').startswith('runtime/'):
            assert digest(ROOT / 'TM3Online_Lobby' / entry['file']) == entry['sha256'].upper(), entry['file']
    assert digest(ROOT / 'TM3Online_Lobby/TM3Lobby.json') == digest(QA / 'before/TM3Lobby.json')
    for name in ('worker_gui.json', 'frozen_installed.json', 'frozen_patch.json'):
        result = json.loads((QA / name).read_text())
        assert result['passed'] and not result['manual_codes_used']
        if name == 'worker_gui.json':
            assert result['live_peer_ping_visible'] and result['peer_ping_new_generation']
        else:
            assert result['peer_ping_measured']
        assert not result['real_cloudflare_deployment'] and not result['real_wan_test']
    runtime = json.loads((QA / 'frozen_runtime.json').read_text())
    assert runtime['passed'] and runtime['runtime']['manual_p2p_ui_removed']
    assert runtime['runtime']['automatic_rooms_available']
    assert runtime['runtime']['peer_latency_available'] and runtime['runtime']['peer_latency_ui']
    assert runtime['runtime']['public_directory_configured'] == bool(PUBLIC_DIRECTORY_URL)
    if PUBLIC_DIRECTORY_URL:
        gui = json.loads((QA / 'public_gui.json').read_text())
        assert gui['passed'] and gui['real_cloudflare_deployment'] and not gui['real_wan_test']
        assert gui['endpoint'] == PUBLIC_DIRECTORY_URL and gui['game_network_simulated']
        assert gui['actual_emulators_connected'] and gui['second_start_new_generation']
        assert gui['closed_room_removed'] and gui['owned_emulators_closed']
        assert gui['live_peer_ping_visible'] and gui['peer_ping_new_generation']
        for name in ('public_installed.json', 'public_patch.json'):
            result = json.loads((QA / name).read_text())
            assert result['passed'] and result['real_cloudflare_deployment']
            assert result['public_https_verified'] and result['public_wss_verified']
            assert result['peer_ping_measured']
            assert result['endpoint'] == PUBLIC_DIRECTORY_URL
            assert result['worker_source_sha256'] == digest(ROOT / 'network/cloudflare/src/worker.js')
            assert not result['real_wan_test'] and not result['cross_isp_gameplay_validated']
    artifacts = {}
    for name in ('TM3Online_Portatil.zip', 'TM3Online_Actualizacion_Salas.zip', 'TM3Online_Directorio_Cloudflare.zip'):
        path = ROOT / name
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            names = archive.namelist()
            assert not any('/node_modules/' in entry or '/.wrangler/' in entry or
                           Path(entry).name in ('.env', '.dev.vars') for entry in names)
            if name == 'TM3Online_Portatil.zip':
                manifest = json.loads(archive.read(PREFIX + 'BUILD_MANIFEST.json'))
                assert manifest['p2p_update']['manual_ui_removed']
                assert manifest['automatic_rooms_update']['public_directory_configured'] == bool(PUBLIC_DIRECTORY_URL)
                assert manifest['automatic_rooms_update']['cloudflare_public_deployment_verified'] == bool(PUBLIC_DIRECTORY_URL)
                assert manifest['automatic_rooms_update']['public_directory_url'] == PUBLIC_DIRECTORY_URL
                assert manifest['latency_update']['version'] == 'peer_rtt_v1'
                assert manifest['latency_update']['sample_window'] == 30
                assert manifest['latency_update']['matched_monotonic_probes_only']
                assert archive.read(PREFIX + 'TM3Lobby.exe') == (ROOT / 'TM3Online_Lobby/TM3Lobby.exe').read_bytes()
                for relative in ('worker_directory.py', 'directory_defaults.py', 'lobby_client.py', 'lobby_entry.py',
                                 'lobby_language.py', 'p2p_session.py', 'test_p2p.py', 'rooms_probe.py',
                                 'cloudflare/src/worker.js', 'cloudflare/package-lock.json'):
                    assert archive.read(PREFIX + 'sources/network/' + relative) == (ROOT / 'network' / relative).read_bytes(), relative
            if name == 'TM3Online_Actualizacion_Salas.zip':
                assert 'TM3Lobby.json' not in names and 'SALAS_AUTOMATICAS_ES.md' in names
                assert archive.read('TM3Lobby.exe') == (ROOT / 'TM3Online_Lobby/TM3Lobby.exe').read_bytes()
        artifacts[name] = dict(bytes=path.stat().st_size, sha256=digest(path))
    report = dict(passed=True, runtime_preserved=True, lobby_config_preserved=True,
                  live_peer_latency_verified=True,
                  manual_code_ui_removed=True, automatic_flow_locally_validated=True,
                  cloudflare_public_deployment=bool(PUBLIC_DIRECTORY_URL),
                  public_directory_url=PUBLIC_DIRECTORY_URL,
                  blocked_on=None if PUBLIC_DIRECTORY_URL else 'Owner publication authorization and verified HTTPS/WSS',
                  real_wan_validated=False, artifacts=artifacts)
    latency_backup = ROOT / 'diagnostics/latency_v1/before'
    assert digest(ROOT / 'TM3Online_Lobby/TM3Lobby.json') == digest(latency_backup / 'TM3Lobby.json')
    assert digest(ROOT / 'TM3Online_Lobby/runtime/TM3Console.ini') == digest(latency_backup / 'TM3Console.ini')
    latency = json.loads((ROOT / 'diagnostics/latency_v1/simulated.json').read_text())
    assert latency['passed'] and not latency['player_network_measured']
    (QA / 'release.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (ROOT / 'diagnostics/latency_v1/release.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
