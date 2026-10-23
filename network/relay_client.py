"""Owned loopback bridge: existing emulator TCP + UDP over one HTTPS tunnel.

The bridge changes only the UDP port in HELLO/ACCEPT. Protocol 7, gameplay,
host/guest authority, cancellation and independent controllers are unchanged.
"""
from __future__ import annotations

import asyncio
import socket
import ssl
import threading
import time

from relay_protocol import (CONTROL, UPGRADE, endpoint, read_frame,
                            validate_game_frame, write_frame)


async def open_tunnel(url, ticket, context=None):
    host, port, path, secure = endpoint(url)
    if context is not None and (context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname):
        raise ValueError("El relay requiere verificar el certificado y el nombre del servidor.")
    async with asyncio.timeout(8):
        reader, writer = await asyncio.open_connection(
            host, port, ssl=(context or ssl.create_default_context()) if secure else None,
            server_hostname=host if secure else None, limit=8192)
        try:
            authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
            writer.write(f"GET {path} HTTP/1.1\r\nHost: {authority}\r\nConnection: Upgrade\r\nUpgrade: {UPGRADE}\r\n\r\n".encode("ascii"))
            await writer.drain()
            header = await reader.readuntil(b"\r\n\r\n")
            lines = header.decode("ascii").lower().split("\r\n")
            headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
            if (len(header) > 8192 or lines[0].split()[:2] != ["http/1.1", "101"] or
                    headers.get("upgrade", "").strip() != UPGRADE):
                raise ValueError("El servidor no ofrece el relay TM3 v1.")
            await write_frame(writer, b"A", ticket.encode("ascii"))
            if await read_frame(reader, 5) != (b"A", b"OK"):
                raise ValueError("El relay rechazo la sesion.")
            return reader, writer
        except BaseException:
            writer.close()
            await writer.wait_closed()
            raise


class LocalDatagrams(asyncio.DatagramProtocol):
    def __init__(self, bridge):
        self.bridge = bridge

    def datagram_received(self, data, address):
        bridge = self.bridge
        if address != bridge.game_udp:
            return
        try:
            validate_game_frame(b"D", data)
            bridge.outgoing.put_nowait((b"D", data))
        except (ValueError, asyncio.QueueFull):
            bridge.dropped += 1  # NetBridge's existing retransmission recovers it.

    def error_received(self, exc):
        pass  # Transient local UDP errors are handled by gameplay retransmission.


class RelayBridge:
    def __init__(self, route, host_port=None, ssl_context=None):
        if route.get("protocol") != 1:
            raise ValueError("Actualiza TM3Lobby para usar este relay.")
        endpoint(route["url"])
        self.url, self.ticket = route["url"], route["ticket"]
        self.host_port, self.ssl_context = host_port, ssl_context
        self.local_port = None
        self.ready, self.done = threading.Event(), threading.Event()
        self.error = ""
        self.thread = None
        self.loop = self.stop_event = None
        self.closing = threading.Event()
        self.game_udp = None
        self.sent = self.received = self.dropped = 0

    def start(self, cancel=None):
        self.thread = threading.Thread(target=self._thread_main, name="TM3RelayBridge", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.ready.wait(.05):
            if self.done.is_set() or time.monotonic() > deadline or (cancel and cancel.is_set()):
                self.close()
                raise ValueError(self.error or "No se pudo abrir el relay de Internet.")
        if self.error:
            self.close()
            raise ValueError(self.error)
        return self

    def close(self):
        self.closing.set()
        try:
            if self.loop and self.stop_event:
                self.loop.call_soon_threadsafe(self.stop_event.set)
        except RuntimeError:
            pass  # Event loop has already finished.
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)

    def _thread_main(self):
        try:
            asyncio.run(self._supervise())
        except Exception as exc:
            if not self.closing.is_set():
                # Never expose ticket contents in errors or logs.
                self.error = "Se perdio la conexion con el relay de Internet (" + type(exc).__name__ + ")."
        finally:
            self.done.set()
            self.ready.set()

    async def _supervise(self):
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()
        work = asyncio.create_task(self._run())
        stop = asyncio.create_task(self.stop_event.wait())
        if self.closing.is_set():
            self.stop_event.set()
        try:
            completed, _ = await asyncio.wait((work, stop), return_when=asyncio.FIRST_COMPLETED)
            if work in completed:
                work.result()
        finally:
            work.cancel()
            stop.cancel()
            await asyncio.gather(work, stop, return_exceptions=True)

    async def _run(self):
        self.outgoing = asyncio.Queue(maxsize=256)
        game = self.loop.create_future()
        server = udp = remote_writer = local_writer = None
        tasks = []

        async def accept(reader, writer):
            if game.done():
                writer.close()
                return
            game.set_result((reader, writer))

        try:
            if self.closing.is_set():
                return
            udp, _ = await self.loop.create_datagram_endpoint(
                lambda: LocalDatagrams(self), local_addr=("127.0.0.1", 0))
            udp_port = udp.get_extra_info("sockname")[1]
            if self.host_port is None:
                server = await asyncio.start_server(accept, "127.0.0.1", 0)
                self.local_port = server.sockets[0].getsockname()[1]
            remote_reader, remote_writer = await open_tunnel(self.url, self.ticket, self.ssl_context)
            if self.host_port is not None:
                pair = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", self.host_port), 3)
                game.set_result(pair)
            self.ready.set()

            async def local_controls():
                reader, writer = await asyncio.wait_for(asyncio.shield(game), 25)
                while True:
                    data = await reader.readexactly(CONTROL.size)
                    validate_game_frame(b"C", data)
                    fields = CONTROL.unpack(data)
                    if fields[2] in (1, 2):
                        if not 0 < fields[3] < 65536:
                            raise ValueError("Puerto UDP local invalido")
                        self.game_udp = ("127.0.0.1", fields[3])
                    await self.outgoing.put((b"C", data))

            async def send():
                while True:
                    kind, data = await self.outgoing.get()
                    await write_frame(remote_writer, kind, data)
                    if kind == b"D":
                        self.sent += 1

            async def receive():
                _, writer = await asyncio.wait_for(asyncio.shield(game), 25)
                while True:
                    kind, data = await read_frame(remote_reader, 40)
                    if kind == b"P" and not data:
                        continue
                    validate_game_frame(kind, data)
                    if kind == b"C":
                        fields = list(CONTROL.unpack(data))
                        if fields[2] in (1, 2):
                            fields[3] = udp_port
                        writer.write(CONTROL.pack(*fields))
                        await asyncio.wait_for(writer.drain(), 5)
                    elif self.game_udp:
                        udp.sendto(data, self.game_udp)
                        self.received += 1

            async def heartbeat():
                while True:
                    await asyncio.sleep(5)
                    await self.outgoing.put((b"P", b""))

            tasks = [asyncio.create_task(coro) for coro in
                     (local_controls(), send(), receive(), heartbeat(), self.stop_event.wait())]
            if self.closing.is_set():
                self.stop_event.set()
            finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if server:
                server.close()
            if udp:
                udp.close()
            if game.done() and not game.cancelled():
                _, local_writer = game.result()
            for writer in (local_writer, remote_writer):
                if writer:
                    writer.close()
                    try:
                        await asyncio.wait_for(writer.wait_closed(), 2)
                    except (OSError, TimeoutError):
                        pass
            if server:
                await server.wait_closed()
