"""Verify real public HTTPS/WSS with the frozen lobby, not cross-ISP gameplay.

Only temporary QA rooms are created. They are removed by rooms_probe's finally
block. The child has no Python in PATH and no access to the player's profile.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / 'diagnostics/rooms_auto_v1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--patch', action='store_true')
    parser.add_argument('--wait', type=int, default=0,
                        help='Seconds allowed for first-deployment HTTPS activation')
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    assert parsed.scheme == 'https' and parsed.hostname
    assert not (parsed.username or parsed.password or parsed.query or parsed.fragment)
    url = args.url.rstrip('/')
    # Default platform CA verification and hostname checking; never ignore TLS.
    deadline = time.monotonic() + args.wait
    while True:
        try:
            with urlopen(Request(url + '/', headers={'User-Agent': 'TM3Lobby/3'}), timeout=20) as response:
                assert response.status == 200
                health = json.load(response)
            break
        except OSError as exc:
            if time.monotonic() >= deadline:
                raise
            print('Public HTTPS not ready: ' + str(exc), flush=True)
            time.sleep(min(15, max(0, deadline - time.monotonic())))
    assert health['service'] == 'TM3Lobby' and health['version'] == 3
    assert health['websocket_rpc'] == 1 and health['automatic_ice'] == 1
    with tempfile.TemporaryDirectory(prefix='tm3_public_rooms_') as folder:
        folder = Path(folder)
        executable = ROOT / 'TM3Online_Lobby/TM3Lobby.exe'
        if args.patch:
            with zipfile.ZipFile(ROOT / 'TM3Online_Actualizacion_Salas.zip') as archive:
                assert 'TM3Lobby.json' not in archive.namelist()
                archive.extractall(folder / 'app')
            executable = folder / 'app/TM3Lobby.exe'
        report = folder / 'probe.json'
        environment = {**os.environ,
                       'PATH': str(Path(os.environ['SystemRoot']) / 'System32'),
                       'LOCALAPPDATA': str(folder)}
        child = subprocess.run([str(executable), '--check-directory', url, str(report)],
                               env=environment, timeout=65)
        result = json.loads(report.read_text(encoding='utf-8'))
        assert child.returncode == 0 and result['passed'], result
        assert result['frozen'] and result['automatic_worker_signaling']
        assert result['manual_codes_used'] is False
        assert result['private_signaling'] and result['native_controls_and_datagrams']
        assert result['peer_ping_measured']
    result.update(endpoint=url, health=health, public_https_verified=True,
                  public_wss_verified=True, real_cloudflare_deployment=True,
                  real_wan_test=False, cross_isp_gameplay_validated=False,
                  python_removed_from_child_path=True,
                  checked_at_utc=datetime.now(timezone.utc).isoformat(),
                  worker_source_sha256=hashlib.sha256(
                      (ROOT / 'network/cloudflare/src/worker.js').read_bytes()).hexdigest().upper())
    name = 'public_patch.json' if args.patch else 'public_installed.json'
    (QA / name).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
