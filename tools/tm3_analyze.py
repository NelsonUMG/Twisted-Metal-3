#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path

KNOWN = {
    "LINKED GAME?": 0x78DBC,
    "WAITING FOR OTHER CONSOLE": 0x78DA0,
    "NEW GAME": 0x78D94,
    "sio:": 0x79EA4,
}
FUNCTIONS = [0x80047728, 0x80047D3C, 0x800518F0, 0x80051970, 0x800519E0]

def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]

def va_to_offset(va: int, text_addr: int) -> int:
    return 0x800 + (va - text_addr)

def main() -> int:
    ap = argparse.ArgumentParser(description="Verifica la revisión SCUS_942.49 de TM3")
    ap.add_argument("exe", type=Path)
    ap.add_argument("--json", type=Path)
    ns = ap.parse_args()
    data = ns.exe.read_bytes()
    if data[:8] != b"PS-X EXE":
        raise SystemExit("ERROR: no es un PS-X EXE")
    text_addr, text_size, entry = u32(data, 0x18), u32(data, 0x1C), u32(data, 0x10)
    report = {
        "path": str(ns.exe),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "entry": f"0x{entry:08X}",
        "text_addr": f"0x{text_addr:08X}",
        "text_size": f"0x{text_size:08X}",
        "strings": {},
        "functions": {},
    }
    ok = True
    for text, expected in KNOWN.items():
        positions = []
        start = 0
        needle = text.encode("ascii")
        while True:
            pos = data.find(needle, start)
            if pos < 0: break
            positions.append(pos); start = pos + 1
        report["strings"][text] = [f"0x{x:X}" for x in positions]
        if expected not in positions: ok = False
    for va in FUNCTIONS:
        off = va_to_offset(va, text_addr)
        chunk = data[off:off+16]
        report["functions"][f"0x{va:08X}"] = {
            "file_offset": f"0x{off:X}", "bytes": chunk.hex(" ")
        }
        if len(chunk) != 16 or chunk == b"\x00"*16: ok = False
    report["known_layout_matches"] = ok
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if ns.json: ns.json.write_text(rendered, encoding="utf-8")
    return 0 if ok else 2

if __name__ == "__main__":
    raise SystemExit(main())
