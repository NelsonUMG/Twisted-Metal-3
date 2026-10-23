from __future__ import annotations
import asyncio, dataclasses, struct, zlib

MAGIC = 0x4F334D54  # bytes: TM3O
VERSION = 1
HEADER = struct.Struct("<IHHIIII")
MAX_PAYLOAD = 60 * 1024

@dataclasses.dataclass(slots=True)
class Packet:
    command: int
    sequence: int
    payload: bytes = b""
    expected_size: int = 0

    def encode(self) -> bytes:
        if len(self.payload) > MAX_PAYLOAD:
            raise ValueError("payload demasiado grande")
        crc = zlib.crc32(self.payload) & 0xFFFFFFFF
        body = HEADER.pack(MAGIC, VERSION, self.command, self.sequence,
                           len(self.payload), self.expected_size, crc) + self.payload
        return struct.pack("<I", len(body)) + body

async def read_packet(reader: asyncio.StreamReader) -> Packet:
    raw_len = await reader.readexactly(4)
    total = struct.unpack("<I", raw_len)[0]
    if total < HEADER.size or total > HEADER.size + MAX_PAYLOAD:
        raise ValueError(f"longitud inválida: {total}")
    body = await reader.readexactly(total)
    magic, version, command, sequence, size, expected, crc = HEADER.unpack_from(body)
    payload = body[HEADER.size:]
    if magic != MAGIC or version != VERSION or size != len(payload):
        raise ValueError("cabecera inválida")
    if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
        raise ValueError("CRC inválido")
    return Packet(command, sequence, payload, expected)
