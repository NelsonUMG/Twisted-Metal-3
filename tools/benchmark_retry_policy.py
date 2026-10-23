"""A/B native protocol fixture over simulated WAN, never a live user session."""
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'network'))
from p2p_session import P2PSession
from ice_nat_lab import NatNetwork, SimulatedP2PSession, isolated_ice_addresses
from verify_ice_nat import fixture


def sender(factor):
    def send(self, data, generation):
        if self.data.readyState != 'open' or not self.game or self.game.generation != generation:
            self.dropped += 1
            return
        delay = max(.008, min(.25, (self.rtt_ms or 50) / 1000 * factor))
        if self.outbox.offer(bytes(data), generation, time.monotonic(), delay):
            self.outbox_ready.set()
        else:
            self.dropped += 1
    return send


def run(factor, seed):
    network = NatNetwork(latency_ms=40, jitter_ms=10, loss=.02, seed=seed)
    peers = []
    try:
        with isolated_ice_addresses(), patch.object(P2PSession, 'send_datagram', sender(factor)):
            peers = [SimulatedP2PSession(network, i) for i in (0, 1)]
            host, guest = peers
            host.accept_answer(guest.create_answer(host.create_offer()))
            assert host.connected.wait(15) and guest.connected.wait(15)
            start = time.monotonic()
            result = fixture(host, guest)
            return dict(factor=factor, seed=seed, seconds=time.monotonic() - start,
                        passed=result['exit_code'] == 0, native_exchanges=300,
                        sent=sum(p.sent for p in peers),
                        coalesced=sum(p.outbox.coalesced for p in peers),
                        network=network.snapshot())
    finally:
        for peer in peers:
            peer.close()


def main():
    results = []
    for seed in (2210, 2211, 2212):
        for factor in ((1, .5) if seed % 2 == 0 else (.5, 1)):
            result = run(factor, seed)
            results.append(result)
            print(json.dumps(result), flush=True)
    target = ROOT / 'diagnostics/retry_ab_v1/results.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(simulated=True, real_game_maps_measured=False,
                                     results=results), indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
