#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("patch", type=Path)
    ap.add_argument("source", type=Path)
    ap.add_argument("output", type=Path)
    ns = ap.parse_args()
    patch = ns.patch.read_bytes()
    if not patch.startswith(b"PATCH") or not patch.endswith(b"EOF"):
        raise SystemExit("IPS inválido")
    out = bytearray(ns.source.read_bytes())
    pos = 5
    while patch[pos:pos+3] != b"EOF":
        off = int.from_bytes(patch[pos:pos+3], "big"); pos += 3
        size = int.from_bytes(patch[pos:pos+2], "big"); pos += 2
        if size == 0:
            rle = int.from_bytes(patch[pos:pos+2], "big"); pos += 2
            val = patch[pos]; pos += 1
            payload = bytes([val]) * rle
        else:
            payload = patch[pos:pos+size]; pos += size
        need = off + len(payload)
        if need > len(out): out.extend(b"\0" * (need-len(out)))
        out[off:need] = payload
    ns.output.write_bytes(out)
    print(f"OK: {ns.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
