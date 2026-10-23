"""Generate a tiny standalone PS-X EXE testing CPU access to extended RAM."""
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parent.parent


def build():
    words = []
    def emit(word): words.append(word)
    def const(reg, value):
        emit(0x3c000000 | reg << 16 | value >> 16)
        emit(0x34000000 | reg << 21 | reg << 16 | value & 0xffff)
    def store(reg, base, offset=0): emit(0xac000000 | base << 21 | reg << 16 | offset)
    def load(reg, base): emit(0x8c000000 | base << 21 | reg << 16); emit(0)
    const(11, 0x80020000)
    for i, address in enumerate((0x81000000, 0x82000000, 0x8fffff00, 0x8ffffffc)):
        const(8, address)
        const(9, 0x4e455400 + i)
        store(9, 8)
        load(10, 8)
        store(10, 11, i * 8)
        const(8, address + 0x20000000)
        load(10, 8)
        store(10, 11, i * 8 + 4)
    const(8, 0x81001000)
    for i, word in enumerate((0x24021234, 0x03e00008, 0)):
        const(9, word)
        store(9, 8, i * 4)
    emit(0x0100f809)  # jalr ra,t0: execute code in extended RAM.
    emit(0)
    store(2, 11, 32)
    const(9, 0x50415353)
    store(9, 11, 36)
    pc = 0x80010000 + len(words) * 4
    emit(0x08000000 | (pc >> 2 & 0x03ffffff)); emit(0)
    payload = struct.pack('<%dI' % len(words), *words)
    payload += bytes((-len(payload)) % 2048)
    header = bytearray(2048)
    header[:8] = b'PS-X EXE'
    struct.pack_into('<5I', header, 0x10, 0x80010000, 0, 0x80010000, len(payload), 0)
    struct.pack_into('<I', header, 0x30, 0x801fff00)
    return bytes(header) + payload


if __name__ == '__main__':
    out = ROOT / 'diagnostics/ram256_v1/ram256_guest.exe'
    candidate = build()
    if out.exists() and out.read_bytes() != candidate:
        raise FileExistsError(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(candidate)
    print(out)
