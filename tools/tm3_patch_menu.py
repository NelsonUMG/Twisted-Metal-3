#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib
from pathlib import Path

OLD = b"LINKED GAME?"
NEW = b"MODO ONLINE?"
EXPECTED_OFFSET = 0x78DBC

def main() -> int:
    ap = argparse.ArgumentParser(description="Parchea solo el texto del menú de TM3")
    ap.add_argument("source", type=Path)
    ap.add_argument("output", type=Path)
    ns = ap.parse_args()
    data = bytearray(ns.source.read_bytes())
    if data[:8] != b"PS-X EXE":
        raise SystemExit("ERROR: archivo no reconocido como PS-X EXE")
    hits = [i for i in range(len(data)) if data.startswith(OLD, i)]
    if hits != [EXPECTED_OFFSET]:
        raise SystemExit(f"ERROR: revisión inesperada; coincidencias={hits}")
    if len(OLD) != len(NEW):
        raise SystemExit("ERROR interno: el reemplazo cambia el tamaño")
    before = hashlib.sha256(data).hexdigest()
    data[EXPECTED_OFFSET:EXPECTED_OFFSET+len(OLD)] = NEW
    ns.output.write_bytes(data)
    after = hashlib.sha256(data).hexdigest()
    print(f"OK: {ns.output}")
    print(f"Offset: 0x{EXPECTED_OFFSET:X}")
    print(f"SHA256 original: {before}")
    print(f"SHA256 parcheado: {after}")
    print("Nota: esto cambia el texto; todavía no reemplaza SIO.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
