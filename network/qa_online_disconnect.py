"""Drive real online WAITING, disconnect P2P, and check runtime termination.

The harness performs the lobby's bridge-close reaction to a retired peer.
This is not a Triangle/menu cancellation test.
"""
import argparse
import json
from pathlib import Path
import time
from qa_role_order import make_fixture
from system256_cable_p2p_qa import DEFAULT_ASSETS, DEFAULT_SETTINGS, start_runtime
from system256_bridge import EngineBridge, System256Peer

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--frozen-exe', type=Path)
    args = parser.parse_args()
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    fixture = output/'fixture.json'; make_fixture(0, 2100, fixture)
    peers = [System256Peer(), System256Peer()]
    bridges = []; runtimes = []
    result = dict(passed=False, external_wan=False)
    try:
        peers[0].accept_answer(peers[1].create_answer(peers[0].create_offer()))
        if not all(p.connected.wait(15) for p in peers): raise TimeoutError('ICE failed')
        bridges = [EngineBridge(peer, 1) for peer in peers]
        for side in (0, 1):
            runtimes.append(start_runtime(side, bridges[side], DEFAULT_ASSETS,
                                          DEFAULT_SETTINGS, fixture, output,
                                          args.frozen_exe.resolve() if args.frozen_exe else None))
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            history = output/'console0/LOG_TM3_ONLINE.txt'
            try:
                log = history.read_text(encoding='utf-8-sig')
                waiting = 'local_yes' in log and 'role_completed' not in log
            except (OSError, ValueError): waiting = False
            if waiting: break
            if any(p[0].poll() is not None for p in runtimes): raise RuntimeError('Premature runtime exit')
            time.sleep(.1)
        else: raise TimeoutError('Did not reach real WAITING')
        started = time.monotonic()
        peers[0].close()
        # Same lifecycle reaction used when the lobby retires a lost session.
        for bridge in bridges: bridge.close()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and any(p[0].poll() is None for p in runtimes):
            time.sleep(.1)
        states = [json.loads(p[2].read_text()) for p in runtimes]
        result.update(seconds_after_disconnect=time.monotonic()-started,
                      exit_codes=[p[0].poll() for p in runtimes], states=states,
                      passed=all(p[0].poll() is not None for p in runtimes) and
                             all(s['state'] == 'failed' for s in states))
    except Exception as exc: result['error'] = repr(exc)
    finally:
        for process, log, *_ in runtimes:
            if process.poll() is None:
                process.terminate()
                try: process.wait(5)
                except Exception: process.kill(); process.wait(5)
            log.close()
        for bridge in bridges: bridge.close()
        for peer in peers: peer.close()
    (output/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)

if __name__ == '__main__': main()
