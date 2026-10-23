from __future__ import annotations
import argparse, asyncio
from protocol import Packet, read_packet

async def run(host: str, port: int, name: str):
    reader, writer = await asyncio.open_connection(host, port)
    for seq in range(1, 6):
        payload = f"{name}: paquete {seq}".encode()
        writer.write(Packet(2, seq, payload, 60000).encode())
        await writer.drain()
        packet = await read_packet(reader)
        print("RECIBIDO", packet.sequence, packet.payload.decode(errors="replace"))
    writer.close(); await writer.wait_closed()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=27888)
    ap.add_argument("--name", required=True)
    ns = ap.parse_args(); asyncio.run(run(ns.host, ns.port, ns.name))
