"""Run both single-console runtimes through real ICE/DTLS/SCTP cable exchange.

This is an integration QA harness, not a remote-WAN certification: both test
peers run on this PC. Cloudflare STUN is used by default, and the public room
directory is health-checked separately; neither service carries game payloads.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

from directory_defaults import PUBLIC_DIRECTORY_URL
from system256_bridge import EngineBridge, System256Peer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSETS = Path(os.environ.get('TM3_QA_ASSETS', str(ROOT / 'runtime/system256')))
DEFAULT_SETTINGS = ROOT / 'config/TM3Console.example.ini'
DEFAULT_FIXTURE = ROOT / '256mb system/reports/reference.json'


def directory_health():
    request = Request(PUBLIC_DIRECTORY_URL, headers={'User-Agent': 'TM3Lobby/3'})
    with urlopen(request, timeout=8) as response:
        value = json.load(response)
    if value.get('service') != 'TM3Lobby' or value.get('automatic_ice') != 1:
        raise RuntimeError('Cloudflare room directory health check failed')
    return value


def start_runtime(side, bridge, assets, settings, fixture, output, frozen_exe=None,
                  delay_online_ms=0, delay_vehicle_ms=0):
    state = output / f'state{side}.json'
    report = output / f'report{side}.json'
    screenshot = output / f'game{side}.bmp'
    log_directory = output / f'console{side}'
    log_directory.mkdir(parents=True, exist_ok=True)
    command = ([str(frozen_exe), '--system256'] if frozen_exe else
        [sys.executable, str(ROOT/'network/system256_runtime.py')])
    command += ['--port', str(bridge.port), '--key', bridge.key.hex(), '--epoch', str(bridge.epoch),
        '--side', str(side), '--assets', str(assets), '--settings', str(settings),
        '--state', str(state), '--qa-fixture', str(fixture), '--qa-report', str(report),
        '--qa-screenshot', str(screenshot), '--qa-resolution', '1',
        '--qa-delay-online-ms', str(delay_online_ms),
        '--qa-delay-vehicle-ms', str(delay_vehicle_ms),
        '--log-directory', str(log_directory)]
    environment = os.environ.copy()
    python_path = [str(ROOT/'network'), str(ROOT/'256mb system/src')]
    if environment.get('PYTHONPATH'):
        python_path.append(environment['PYTHONPATH'])
    environment['PYTHONPATH'] = os.pathsep.join(python_path)
    environment['SDL_VIDEODRIVER'] = 'dummy'
    environment['SDL_AUDIODRIVER'] = 'dummy'
    environment['TM3O_STANDARD_PS1'] = '0'
    environment['TM3O_DIAGNOSTICS'] = '0'
    log = (output / f'process{side}.log').open('wb')
    process = subprocess.Popen(command, cwd=ROOT, env=environment,
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
    return process, log, state, report, screenshot


def wait_for_runtimes(items, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(item[0].poll() is not None and item[3].is_file() for item in items):
            return
        for side, item in enumerate(items):
            if item[0].poll() not in (None, 0):
                try:
                    detail = item[2].read_text(encoding='utf-8')
                except OSError:
                    detail = '(no state file)'
                raise RuntimeError(f'Runtime {side} exited with {item[0].returncode}: {detail}')
        time.sleep(.1)
    states = []
    for item in items:
        try:
            states.append(json.loads(item[2].read_text(encoding='utf-8')))
        except (OSError, ValueError):
            states.append(None)
    raise TimeoutError(f'P2P single-console QA timeout; states={states}')


def run(args):
    output = Path(args.output or ROOT/'diagnostics/system256_cable_p2p_qa'/f'run_{time.time_ns()}').resolve()
    output.mkdir(parents=True, exist_ok=True)
    health = directory_health()
    peers = []
    bridges = []
    runtimes = []
    try:
        host, guest = System256Peer(), System256Peer()
        peers.extend((host, guest))
        offer = host.create_offer()
        answer = guest.create_answer(offer)
        host.accept_answer(answer)
        if not host.connected.wait(12) or not guest.connected.wait(12):
            raise TimeoutError(f'ICE did not connect: host={host.error!r} guest={guest.error!r}')
        generation = 1
        bridges = [EngineBridge(host, generation), EngineBridge(guest, generation)]
        for side in (0, 1):
            runtimes.append(start_runtime(side, bridges[side], Path(args.guest_assets if side == 1 and args.guest_assets else args.assets).resolve(),
                Path(args.settings).resolve(), Path(args.fixture).resolve(), output,
                Path(args.frozen_exe).resolve() if args.frozen_exe else None,
                args.qa_delay_online_ms, args.qa_delay_vehicle_ms))
        wait_for_runtimes(runtimes, args.timeout)
        reports = [json.loads(item[3].read_text(encoding='utf-8')) for item in runtimes]
        ice = host.snapshot()
        fixture_data = json.loads(Path(args.fixture).read_text(encoding='utf-8'))
        required_waits = fixture_data.get('qa_wait_screens', [])
        wait_captures = {phase: [r.get('wait_screenshots', {}).get(phase)
                                 for r in reports
                                 if r.get('wait_screenshots', {}).get(phase)]
                         for phase in required_waits}
        waits_visible = all(wait_captures.get(phase) for phase in required_waits)
        passed = all(r.get('completed') and r.get('architecture') == 'one_console_per_pc'
                     and r.get('local_core_count') == 1
                     and r.get('gameplay_ticks') == 600
                     and r.get('time_mismatches') == 0 and r.get('rng_mismatches') == 0
                     and not r.get('audio_error') and r.get('audio_started')
                     and r.get('video_frames_rendered', 0) > 0 for r in reports) and waits_visible
        result = dict(passed=passed, test='real ICE/DTLS/SCTP cable exchange; same-PC two-process peers',
            external_wan=False, cloudflare_directory=health,
            ice=dict(connected=host.connected.is_set() and guest.connected.is_set(),
                     candidates=ice.get('candidates'), selected=ice.get('selected'),
                     rtt=ice.get('latency')),
            reports=reports,
            required_wait_phases=required_waits,
            waiting_screenshots=wait_captures,
            screenshots=[str(item[4]) for item in runtimes],
            logs=[str(output / f'process{side}.log') for side in (0, 1)])
        (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    finally:
        for item in runtimes:
            process, log = item[0], item[1]
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(5)
            log.close()
        for bridge in bridges:
            bridge.close()
        for peer in peers:
            peer.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', default=str(DEFAULT_ASSETS))
    parser.add_argument('--guest-assets', help='Alternate assets for a mixed Vulkan/software test.')
    parser.add_argument('--settings', default=str(DEFAULT_SETTINGS))
    parser.add_argument('--fixture', default=str(DEFAULT_FIXTURE))
    parser.add_argument('--output')
    parser.add_argument('--frozen-exe', help='Run the real portable frozen executable instead of Python source.')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--qa-delay-online-ms', type=int, default=0,
                        help='Test-only delay for the peer online-mode handshake.')
    parser.add_argument('--qa-delay-vehicle-ms', type=int, default=0,
                        help='Test-only delay for the peer vehicle-select transfer.')
    args = parser.parse_args()
    for path in (Path(args.assets)/'beetle_psx_system256.dll',
                 Path(args.assets)/'TM3_SYSTEM256.cue', Path(args.fixture), Path(args.settings)):
        if not path.is_file():
            parser.error(f'Required test file is missing: {path}')
    if args.frozen_exe and not Path(args.frozen_exe).is_file():
        parser.error(f'Frozen executable is missing: {args.frozen_exe}')
    result = run(args)
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
