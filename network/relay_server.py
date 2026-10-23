"""Authenticated TM3 relay. Internet access requires the supplied HTTPS proxy."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import logging
import os
import time

from relay_protocol import (UPGRADE, loopback, read_frame, validate_game_frame,
                            validate_secret, verify_ticket, write_frame)

LOG = logging.getLogger("tm3relay")


@dataclass
class Seat:
    writer: asyncio.StreamWriter
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    peer: "Seat | None" = None
    closed: bool = False


class Relay:
    def __init__(self, secret, max_connections=128, pair_timeout=30,
                 idle_timeout=20, max_session=21600):
        self.secret = validate_secret(secret)
        self.max_connections = max_connections
        self.pair_timeout, self.idle_timeout, self.max_session = pair_timeout, idle_timeout, max_session
        self.rooms = {}
        self.connections = 0
        self.tasks = set()

    async def accept(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        session = side = seat = None
        admitted = False
        try:
            if self.connections >= self.max_connections:
                return
            self.connections += 1
            admitted = True
            async with asyncio.timeout(5):
                header = await reader.readuntil(b"\r\n\r\n")
            lines = header.decode("ascii").split("\r\n")
            headers = dict(line.lower().split(":", 1) for line in lines[1:] if ":" in line)
            if (len(header) > 8192 or lines[0] != "GET /tm3-relay HTTP/1.1" or
                    headers.get("upgrade", "").strip() != UPGRADE or
                    "upgrade" not in [v.strip() for v in headers.get("connection", "").split(",")]):
                raise ValueError("Upgrade requerido")
            writer.write(f"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: {UPGRADE}\r\n\r\n".encode())
            await asyncio.wait_for(writer.drain(), 5)
            kind, ticket = await read_frame(reader, 5)
            if kind != b"A":
                raise ValueError("Autenticacion requerida")
            claims = verify_ticket(self.secret, ticket.decode("ascii"))
            session, side = claims["session"], claims["side"]
            room = self.rooms.setdefault(session, {})
            if side in room:
                raise ValueError("Puesto ocupado")
            seat = room[side] = Seat(writer)
            # Admit before pairing so the host can signal readiness to the lobby.
            await write_frame(writer, b"A", b"OK")
            other = room.get(1 - side)
            if other:
                seat.peer, other.peer = other, seat
                seat.ready.set()
                other.ready.set()
            await asyncio.wait_for(seat.ready.wait(), self.pair_timeout)
            if seat.closed:
                return
            deadline = time.monotonic() + self.max_session
            credit, updated = 2 * 1024 * 1024, time.monotonic()
            while time.monotonic() < deadline:
                kind, data = await read_frame(reader, self.idle_timeout)
                now = time.monotonic()
                credit = min(2 * 1024 * 1024, credit + (now - updated) * 1024 * 1024) - len(data) - 3
                updated = now
                if credit < 0:
                    raise ValueError("Limite de trafico excedido")
                if kind == b"P" and not data:
                    await write_frame(writer, b"P")
                    continue
                validate_game_frame(kind, data)
                if seat.peer.closed:
                    break
                await write_frame(seat.peer.writer, kind, data)
        except (OSError, ValueError, UnicodeError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError, TimeoutError):
            # Exception messages may contain tickets. Never log them.
            LOG.debug("Relay connection ended")
        finally:
            if seat:
                seat.closed = True
                seat.ready.set()
                if seat.peer:
                    seat.peer.closed = True
                    seat.peer.ready.set()
                    seat.peer.writer.close()
                room = self.rooms.get(session, {})
                if room.get(side) is seat:
                    del room[side]
                if not room:
                    self.rooms.pop(session, None)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            if admitted:
                self.connections -= 1
            self.tasks.discard(task)

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def serve(args):
    relay = Relay(os.environ.get("TM3_RELAY_SECRET", ""), args.max_connections)
    if not loopback(args.bind) and not args.behind_proxy:
        raise ValueError("Usa loopback o --behind-proxy dentro de una red privada sin publicar el puerto.")
    server = await asyncio.start_server(relay.accept, args.bind, args.port, limit=8192)
    LOG.info("TM3 relay v1 listening; HTTPS termination required for Internet access")
    try:
        async with server:
            await server.serve_forever()
    finally:
        await relay.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=27900)
    parser.add_argument("--max-connections", type=int, default=128)
    parser.add_argument("--behind-proxy", action="store_true")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(parser.parse_args()))


if __name__ == "__main__":
    main()
