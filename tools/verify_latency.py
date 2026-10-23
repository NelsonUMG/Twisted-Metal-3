"""Validate peer RTT over real ICE/DTLS/SCTP with known simulated delays.

No router or adapter changes and no test rooms on the public directory. These
numbers are laboratory measurements, NOT the player's home/mobile latency.
"""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'network'))
from ice_nat_lab import NatNetwork, SimulatedP2PSession, isolated_ice_addresses


def check(one_way_ms, jitter_ms):
    network = NatNetwork(latency_ms=one_way_ms, jitter_ms=jitter_ms)
    peers = []
    try:
        with isolated_ice_addresses():
            peers = [SimulatedP2PSession(network, side) for side in (0, 1)]
            host, guest = peers
            answer = guest.create_answer(host.create_offer())
            host.accept_answer(answer)
            assert host.connected.wait(8) and guest.connected.wait(8)
            deadline = time.monotonic() + 14
            while time.monotonic() < deadline:
                if all(p.latency_snapshot()['samples'] >= 4 for p in peers):
                    break
                time.sleep(.03)
            results = [p.latency_snapshot() for p in peers]
            for result in results:
                assert result['samples'] >= 4 and not result['stale'], result
                assert result['method'] == 'encrypted_control_echo'
                assert result['minimum_ms'] >= 2 * (one_way_ms - jitter_ms) - 3, result
                assert result['average_ms'] < 2 * (one_way_ms + jitter_ms) + 500, result
                assert result['variation_ms'] >= 0
            return dict(configured_one_way_ms=one_way_ms, configured_jitter_ms=jitter_ms,
                        game_network_simulated=True, peers=results)
    finally:
        for peer in peers:
            peer.close()


def main():
    cases = [check(15, 0), check(80, 10)]
    assert cases[1]['peers'][0]['average_ms'] > cases[0]['peers'][0]['average_ms'] + 50
    report = dict(passed=True, measurement='peer round-trip time (RTT)',
                  player_network_measured=False, public_directory_in_ping_path=False,
                  wire_compatible_with_existing_peers=True, cases=cases)
    target = ROOT / 'diagnostics/latency_v1/simulated.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
