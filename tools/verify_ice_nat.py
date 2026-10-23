"""Production ICE + native TM3 NetBridge across a TEST-ONLY simulated Internet.

This is NOT a real WAN / mobile-data test. Run from the workspace:
tools/.venv_lobby/Scripts/python.exe tools/verify_ice_nat.py
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'network'))
from ice_nat_lab import NatNetwork, NatPolicy, PUBLIC_IPS, SimulatedP2PSession, isolated_ice_addresses
from lobby_client import listening
from verify_linked_startup import wait_for


SCENARIOS = {
    'double_nat': dict(),
    'loss_jitter': dict(latency_ms=10, jitter_ms=5, loss=.02, seed=2201),
    'mobile_latency': dict(latency_ms=40, jitter_ms=10, loss=.01, seed=2210),
    'one_symmetric': dict(policies=(NatPolicy(filtering='endpoint-independent'),
                                   NatPolicy(mapping='address-port-dependent'))),
    'two_symmetric': dict(policies=(NatPolicy(mapping='address-port-dependent'),) * 2),
    'udp_blocked': dict(block_peer_udp=True),
}
NEGATIVE = {'two_symmetric', 'udp_blocked'}


def fixture(host, guest):
    guest_port = guest.attach_game()
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith('TM3O_')}
    env.update(TM3_QA_HOST_PORT=str(port), TM3_QA_JOIN_PORT=str(guest_port),
               TM3O_LINK_HIRES_WAIT='1', TM3O_LINK_UDP_WAKE='1')
    process = subprocess.Popen([str(ROOT / 'diagnostics/lobby_console_v1/build/Release/TM3NetRelayTest.exe')],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_for(lambda: listening(process.pid, port) or process.poll() is not None,
                 5, 'Native fixture did not listen')
        assert process.poll() is None, 'Native fixture exited before attaching bridge'
        host.attach_game(port)
        output, _ = process.communicate(timeout=100)
        assert process.returncode == 0, f'Native fixture exit={process.returncode}: {output}'
        assert host.sent and host.received and guest.sent and guest.received
        return dict(exit_code=process.returncode, output=output.strip(),
                    native_roles=[2, 1], fragmented_bytes_each_way=65536,
                    native_exchanges=300, payload_bytes=60,
                    cancel_preserved_connection=True)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)


def next_message(peer, token):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            kind, value = peer.events.get(timeout=.2)
        except queue.Empty:
            continue
        if kind == 'message' and value == token:
            return
        if kind == 'error':
            raise AssertionError(value)
    raise AssertionError('Reliable control message did not arrive')


def scenario(name):
    network = NatNetwork(**SCENARIOS[name])
    host = guest = None
    report = dict(scenario=name, expected='blocked_without_relay' if name in NEGATIVE else 'connected')
    started = time.monotonic()
    try:
        host, guest = SimulatedP2PSession(network, 0), SimulatedP2PSession(network, 1)
        answer = guest.create_answer(host.create_offer())
        host.accept_answer(answer)
        deadline = time.monotonic() + (68 if name in NEGATIVE else 20)
        while not (host.connected.is_set() and guest.connected.is_set()):
            if host.done.is_set() or guest.done.is_set() or time.monotonic() >= deadline:
                break
            time.sleep(.02)
        connected = host.connected.is_set() and guest.connected.is_set()
        if name in NEGATIVE:
            assert not connected, 'Unexpected bypass: restricted NAT peers connected'
            # Exercise the real production failure path, not a shortened mock timeout.
            assert host.done.wait(8), 'Host ICE did not report failure/timeout'
            assert 'ICE' in host.error, host.error
            assert network.counts['dtls_delivered'] == 0
            report['host_failure_reported'] = True
            report['guest_manual_wait_cancelled_by_test'] = True
        else:
            assert connected, (host.error, guest.error, network.snapshot())
            paths = [host.selected_path(), guest.selected_path()]
            for side, path in enumerate(paths):
                assert len(path) == 1 and path[0]['remote'][0] == PUBLIC_IPS[1 - side], path
            assert all(peer.snapshot()['candidates'].get('srflx') == 1 for peer in (host, guest))
            report['selected_paths'] = paths  # Documentation-range IPs, not personal addresses.
            host.send_message({'test': name, 'side': 'host'})
            guest.send_message({'test': name, 'side': 'guest'})
            next_message(guest, {'test': name, 'side': 'host'})
            next_message(host, {'test': name, 'side': 'guest'})
            report['reliable_control_both_directions'] = True
            report['native_fixture'] = fixture(host, guest)
            report['host'], report['guest'] = host.snapshot(), guest.snapshot()
            assert network.counts['dtls_delivered'] > 0
            assert network.counts['unroutable_destination'] > 0  # LAN attempt denied.
            if name == 'loss_jitter':
                assert network.counts['random_loss'] > 0
            if name == 'one_symmetric':
                assert any(p[0]['remote_type'] == 'prflx' for p in paths), paths
        report['passed'] = True
    except Exception as exc:
        report.update(passed=False, failure=f'{type(exc).__name__}: {exc}')
    finally:
        if host:
            report.setdefault('host', host.snapshot())
        if guest:
            report.setdefault('guest', guest.snapshot())
        for peer in (host, guest):
            if peer:
                peer.close()
        report['cleanup_threads_stopped'] = all(not peer.thread.is_alive() for peer in (host, guest) if peer)
        report['network'] = network.snapshot()
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=SCENARIOS, action='append')
    parser.add_argument('--repeat', type=int, default=1, help='Repeat positive cases only (1-10)')
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10:
        parser.error('--repeat must be between 1 and 10')
    names = args.scenario or list(SCENARIOS)
    started = datetime.now(timezone.utc).isoformat()
    with isolated_ice_addresses():
        # Avoid cross-test GIL / timer / CPU interference during bulk transfers.
        results = []
        for iteration in range(args.repeat):
            for name in names:
                if name not in NEGATIVE:
                    result = scenario(name)
                    result['iteration'] = iteration + 1
                    results.append(result)
        # Idle negative cases may use their real 60-second deadline concurrently.
        with ThreadPoolExecutor(max_workers=2) as pool:
            results += list(pool.map(scenario, [name for name in names if name in NEGATIVE]))
    report = dict(version='ice_nat_simulation_v1', started_utc=started,
                  real_wan_test=False, real_hotspot_test=False,
                  os_network_settings_modified=False,
                  boundary='Only ICE UDP sockets virtualized; ICE/STUN/DTLS/SCTP and native C++ bridge are real.',
                  limitations=['No real ISP, mobile radio, OS firewall or router firmware exercised.',
                               'No bandwidth/congestion, MTU blackhole, IPv6, NAT expiry or rebinding model.',
                               'No complete human race or four-player validation.'],
                  scenarios=results,
                  passed=all(result['passed'] and result['cleanup_threads_stopped'] for result in results))
    output = ROOT / 'diagnostics/ice_p2p_v1/nat_simulation.json'
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    output.write_text(encoded, encoding='utf-8')
    history = output.with_name('nat_simulation_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    history.write_text(encoded, encoding='utf-8')
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {output}", flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
