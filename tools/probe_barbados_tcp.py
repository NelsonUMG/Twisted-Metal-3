"""Small public Speedtest TCP handshake probe, NOT a bandwidth test."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import time


def measure(host):
    values, errors = [], []
    address = socket.gethostbyname(host)
    for _ in range(5):
        start = time.perf_counter()
        try:
            with socket.create_connection((address, 8080), timeout=2):
                values.append(round((time.perf_counter()-start)*1000, 2))
        except OSError as exc:
            errors.append(type(exc).__name__)
        time.sleep(.2)
    return dict(host=host, ipv4=address, port=8080, method='TCP connection handshake; DNS excluded',
                samples_ms=values, errors=errors,
                average_ms=round(sum(values)/len(values), 2) if values else None)


if __name__ == '__main__':
    hosts=['speedtest.flowbarbados.co', 'speedtest.digicelbarbados.net']
    with ThreadPoolExecutor(2) as pool: results=list(pool.map(measure, hosts))
    report=dict(measured_utc=datetime.now(timezone.utc).isoformat(), source='this Windows PC',
                actual_friend_connection=False, results=results)
    target=Path(__file__).resolve().parent.parent/'diagnostics/barbados_tcp.json'
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
