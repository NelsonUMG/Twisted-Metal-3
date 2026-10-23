"""Real ICE behind simulated NAT, answer deliberately applied after 80 seconds."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'network'))
from ice_nat_lab import NatNetwork, SimulatedP2PSession, isolated_ice_addresses

with isolated_ice_addresses():
    network = NatNetwork()
    host, guest = SimulatedP2PSession(network, 0), SimulatedP2PSession(network, 1)
    try:
        answer = guest.create_answer(host.create_offer())
        print('Answer generated; deliberately waiting 80 seconds.', flush=True)
        time.sleep(40)
        print('40 seconds; continuing manual-transfer wait.', flush=True)
        time.sleep(40)
        assert not guest.done.is_set(), guest.error
        print(json.dumps(dict(before_host=host.snapshot(), before_guest=guest.snapshot(), network=network.snapshot())), flush=True)
        host.accept_answer(answer)
        assert host.connected.wait(20) and guest.connected.wait(20), (host.snapshot(), guest.snapshot(), network.snapshot())
        report = dict(passed=True, delayed_answer_seconds=80, real_wan=False,
                      host=host.snapshot(), guest=guest.snapshot())
        (ROOT / 'diagnostics/ice_p2p_v1/delayed_answer.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
    finally:
        host.close()
        guest.close()
