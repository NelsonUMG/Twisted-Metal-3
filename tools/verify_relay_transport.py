"""Shipping C++ NetBridge over two Python relay bridges on loopback sockets."""
import os
from pathlib import Path
import socket
import subprocess
from verify_linked_startup import TestRelay, listening, wait_for

ROOT = Path(__file__).resolve().parent.parent


def main():
    relay = TestRelay()
    process = None
    try:
        guest = relay.bridge(1)
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        environment = {k: v for k, v in os.environ.items() if not k.startswith('TM3O_')}
        environment.update(TM3_QA_HOST_PORT=str(port), TM3_QA_JOIN_PORT=str(guest.local_port),
                           TM3O_LINK_HIRES_WAIT='1', TM3O_LINK_UDP_WAKE='1')
        exe = ROOT / 'diagnostics/lobby_console_v1/build/Release/TM3NetRelayTest.exe'
        process = subprocess.Popen([str(exe)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        wait_for(lambda: listening(process.pid, port) or process.poll() is not None, 5, 'Fixture did not listen')
        if process.poll() is not None:
            raise RuntimeError(process.communicate()[0])
        host = relay.bridge(0, port)
        output, _ = process.communicate(timeout=40)
        print(output, end='')
        assert process.returncode == 0, f'C++ relay test exit={process.returncode}'
        assert host.sent and guest.sent and host.received and guest.received
        print(f'PASS: relay datagrams host sent/received={host.sent}/{host.received}, guest={guest.sent}/{guest.received}')
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
        relay.close()


if __name__ == '__main__':
    main()
