"""Functional QA for Vulkan negotiation and synchronized software fallback."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT/'network'), str(ROOT/'256mb system/src')]
from system256_bridge import System256Peer, EngineBridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('both', 'mixed'), required=True,
                        help='both = Vulkan available to both peers; mixed = peer 1 uses software only.')
    parser.add_argument('--exe', required=True, help='Fresh frozen TM3Lobby executable.')
    parser.add_argument('--one-way-ms', type=int, default=0,
                        help='Optional test-only delay for controller inputs, per direction.')
    args = parser.parse_args()
    if not 0 <= args.one_way_ms <= 1000:
        parser.error('--one-way-ms must be between 0 and 1000')
    exe = Path(args.exe).resolve()
    assets = ROOT/'diagnostics/vulkan_trial_20261022/frozen_vulkan_assets'
    settings = ROOT/'dist/TM3Online_UI2_175_20261021/runtime/TM3Console.ini'
    fixture = ROOT/'256mb system/reports/reference.json'
    for path in (exe, assets/'TM3_SYSTEM256.bin', assets/'TM3_SYSTEM256.cue',
                 assets/'beetle_psx_system256.dll',
                 assets/'beetle_psx_system256_vulkan.dll',
                 assets/'tm3_vulkan_frontend.dll', settings, fixture):
        if not path.is_file():
            raise FileNotFoundError(path)

    work = ROOT/'diagnostics/vulkan_trial_20261022'/f'qa_{args.mode}_{time.time_ns()}'
    work.mkdir(parents=True)
    peers = [System256Peer(), System256Peer()]
    bridges, processes, logs = [], [], []
    try:
        peers[0].accept_answer(peers[1].create_answer(peers[0].create_offer()))
        if not all(peer.connected.wait(30) for peer in peers):
            raise RuntimeError(f'ICE failed to connect: {[peer.error for peer in peers]}')

        side_assets = [assets, assets]
        with tempfile.TemporaryDirectory(prefix='tm3_vulkan_fallback_') as temporary:
            if args.mode == 'mixed':
                side_assets[1] = Path(temporary)/'software_peer'
                side_assets[1].mkdir()
                for name in ('TM3_SYSTEM256.bin', 'TM3_SYSTEM256.cue',
                             'beetle_psx_system256.dll', 'libwinpthread-1.dll'):
                    source = assets/name
                    target = side_assets[1]/name
                    try:
                        os.link(source, target)
                    except OSError:
                        shutil.copy2(source, target)
                # Deliberately omit both Vulkan components: the same normal
                # software core should be selected by both clients.
            environment = dict(os.environ)
            environment.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
            for side, peer in enumerate(peers):
                bridge = EngineBridge(peer, 1)
                bridges.append(bridge)
                log = (work/f'peer{side}.log').open('w', encoding='utf-8')
                logs.append(log)
                command = [str(exe), '--system256', '--port', str(bridge.port),
                           '--key', bridge.key.hex(), '--epoch', str(bridge.epoch),
                           '--side', str(side), '--delay', '2', '--assets', str(side_assets[side]),
                           '--settings', str(settings), '--state', str(work/f'state{side}.json'),
                           '--qa-fixture', str(fixture), '--qa-report', str(work/f'peer{side}.json'),
                           '--qa-one-way-delay-ms', str(args.one_way_ms),
                           '--qa-resolution', '1']
                processes.append(subprocess.Popen(command, env=environment,
                                                  stdout=log, stderr=log))

            deadline = time.monotonic()+150
            while any(process.poll() is None for process in processes) and time.monotonic() < deadline:
                time.sleep(.2)
            if any(process.poll() is None for process in processes):
                raise TimeoutError('Vulkan QA exceeded 150 seconds.')
            if not all(process.returncode == 0 for process in processes):
                raise RuntimeError(f'Runtime errors; inspect {work}')

        rows = [json.loads((work/f'peer{side}.json').read_text(encoding='utf-8')) for side in (0, 1)]
        expected = 'vulkan' if args.mode == 'both' else 'software'
        checks = []
        for row in rows:
            checks.append(
                row.get('completed') is True and row.get('gameplay_ticks') == 600 and
                row.get('rate', 0) >= 29 and row.get('time_mismatches') == 0 and
                row.get('rng_mismatches') == 0 and row.get('video_backend') == expected and
                (expected != 'vulkan' or bool(row.get('video_adapter'))) and
                row.get('audio_error') is None and row.get('audio_started') is True and
                row.get('audio_output_bytes', 0) > 0 and
                row.get('audio_start_delay_ms') is not None and
                row.get('audio_start_delay_ms') < 80 and
                row.get('video_frames_rendered', 0) > 0 and
                row.get('delayed_input_packet_drops') == 0)
        result = dict(passed=all(checks), mode=args.mode, expected_backend=expected,
                      executable=str(exe), real_ice=True, actual_remote_wan=False,
                      simulated_rtt_ms=args.one_way_ms*2, controller_lead_ms=33.37,
                      audio_device='SDL dummy for QA; game audio is local per PC and not networked',
                      results=rows, peer_passed=checks, work_dir=str(work))
        (work/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
        return 0 if result['passed'] else 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        for bridge in bridges:
            bridge.close()
        for peer in peers:
            peer.close()
        for log in logs:
            log.close()


if __name__ == '__main__':
    raise SystemExit(main())
