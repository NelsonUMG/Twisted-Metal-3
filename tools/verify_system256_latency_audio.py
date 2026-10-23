"""Test portable SYSTEM256 audio with simulated 80 ms RTT.

The test delays only confirmed-input packets (40 ms in each direction). ICE,
the packaged executable/assets, deterministic fixture, low-delay local audio
queue, and video path are exercised. This is not a Barbados/WAN or Cloudflare
path test; the reported audio start delay measures software scheduling only,
not physical speaker latency.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT/'network'), str(ROOT/'256mb system/src')]
from system256_bridge import System256Peer, EngineBridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package-root', required=True,
                        help='Extracted portable folder containing TM3Lobby.exe and runtime/.')
    parser.add_argument('--one-way-ms', type=int, default=40)
    parser.add_argument('--control-delay-frames', type=int, default=2)
    parser.add_argument('--resolution', type=int, choices=(1, 2, 4), default=None,
                        help='Override internal render scale for the A/B CPU/video test.')
    args = parser.parse_args()
    if not 0 < args.one_way_ms <= 500:
        parser.error('--one-way-ms must be between 1 and 500')
    if not 1 <= args.control_delay_frames <= 120:
        parser.error('--control-delay-frames must be 1..120')

    package = Path(args.package_root).resolve()
    exe = package/'TM3Lobby.exe'
    assets = package/'runtime/system256'
    settings = package/'runtime/TM3Console.ini'
    fixture = ROOT/'256mb system/reports/reference.json'
    required = (exe, assets/'TM3_SYSTEM256.bin', assets/'TM3_SYSTEM256.cue',
                assets/'beetle_psx_system256.dll', settings, fixture)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError('Portable QA assets missing: ' + ', '.join(missing))
    if zipfile.is_zipfile(package):
        raise ValueError('Pass the extracted portable folder, not the ZIP itself.')

    work = ROOT/'diagnostics/system256_latency_audio_qa'/f'run_{time.time_ns()}'
    work.mkdir(parents=True, exist_ok=True)
    peers = [System256Peer(), System256Peer()]
    bridges = []
    processes = []
    logs = []
    try:
        answer = peers[1].create_answer(peers[0].create_offer())
        peers[0].accept_answer(answer)
        if not all(peer.connected.wait(30) for peer in peers):
            raise RuntimeError('ICE did not connect: ' + repr([peer.error for peer in peers]))

        environment = dict(os.environ)
        environment.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
        for side, peer in enumerate(peers):
            bridge = EngineBridge(peer, 1)
            bridges.append(bridge)
            log_path = work/f'child{side}.log'
            log = log_path.open('w', encoding='utf-8')
            logs.append(log)
            command = [str(exe), '--system256', '--port', str(bridge.port),
                       '--key', bridge.key.hex(), '--epoch', str(bridge.epoch),
                       '--side', str(side), '--delay', str(args.control_delay_frames), '--assets', str(assets),
                       '--settings', str(settings), '--state', str(work/f'state{side}.json'),
                       '--qa-fixture', str(fixture), '--qa-report', str(work/f'child{side}.json'),
                       '--qa-one-way-delay-ms', str(args.one_way_ms),
                       '--qa-screenshot', str(work/f'gameplay{side}.bmp')]
            if args.resolution is not None:
                command.extend(['--qa-resolution', str(args.resolution)])
            processes.append(subprocess.Popen(command, env=environment, stdout=log, stderr=log))

        deadline = time.monotonic() + 180
        while any(process.poll() is None for process in processes) and time.monotonic() < deadline:
            time.sleep(.25)
        if any(process.poll() is None for process in processes):
            raise TimeoutError('Portable runtime exceeded 180 seconds.')
        if not all(process.returncode == 0 for process in processes):
            raise RuntimeError('Frozen portable runtime failed: ' + repr([p.returncode for p in processes]))

        rows = [json.loads((work/f'child{side}.json').read_text(encoding='utf-8'))
                for side in (0, 1)]
        checkpoints = json.loads(fixture.read_text(encoding='utf-8'))['checkpoints']
        expected_hashes = [console['ram_sha256'] for console in checkpoints[-1]['consoles']]
        screenshots = [work/f'gameplay{side}.bmp' for side in (0, 1)]
        child_ok = []
        for side, row in enumerate(rows):
            child_ok.append(
                row.get('completed') is True and row.get('gameplay_ticks') == 600 and
                row.get('rate', 0) >= 29 and row.get('time_mismatches') == 0 and
                row.get('rng_mismatches') == 0 and row.get('hashes') == expected_hashes and
                row.get('audio_error') is None and row.get('audio_started') is True and
                row.get('audio_start_delay_ms') is not None and row.get('audio_start_delay_ms') < 80 and
                row.get('audio_underruns') == 0 and
                row.get('audio_output_bytes', 0) > 0 and row.get('pcm_generated_bytes', 0) > 0 and
                row.get('pcm_queue_dropped_bytes') == 0 and row.get('pcm_stale_dropped_bytes') == 0 and
                row.get('video_frames_rendered', 0) >= 500 and
                row.get('video_frames_presented', 0) >= 500 and
                row.get('delay') == args.control_delay_frames and
                abs(row.get('controller_lead_ms', 0) - args.control_delay_frames * 1000 / 59.94) < .02 and
                row.get('simulated_rtt_ms') == args.one_way_ms * 2 and
                row.get('delayed_input_packet_drops') == 0 and screenshots[side].is_file() and
                screenshots[side].stat().st_size > 1024 and
                screenshots[side].read_bytes()[:2] == b'BM')

        result = dict(passed=all(child_ok), portable_executable=str(exe),
                      software_renderer=True, audio_device='SDL dummy (functional queue test)',
                      video_device='SDL dummy (captured full gameplay frame)',
                      real_ice=True, actual_remote_wan=False, cloudflare_room_directory=False,
                      simulated_one_way_ms=args.one_way_ms,
                      simulated_rtt_ms=args.one_way_ms*2, jitter_ms=0, loss_percent=0,
                      audio_prebuffer_ms=0,
                      controller_delay_frames=args.control_delay_frames,
                      controller_lead_ms=round(args.control_delay_frames * 1000 / 59.94, 2),
                      internal_resolution=rows[0].get('internal_resolution'),
                      minimum_game_rate=29, screenshots=[str(path) for path in screenshots],
                      results=rows, child_passed=child_ok)
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
