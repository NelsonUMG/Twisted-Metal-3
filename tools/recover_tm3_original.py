#!/usr/bin/env python3
"""Recover the byte-identical retail SCUS from the preserved menu-only backup.

The first TM3 Online experiment changed only the 12-byte menu label.  Keeping
this transformation as a small, hash-guarded tool makes the PSXRecomp input
reproducible without overwriting any of the preserved patched executables.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


MENU_ONLY_SHA256 = (
    "24fc2707d63ceaab857105c6b9bbf1e344054ace116c97d538c478310ba4d765"
)
ORIGINAL_SHA256 = (
    "2bb2a618889a057627a79d2a01cd53b83c6dbc12b9ea49a5f621b6179c5e8998"
)
MENU_OFFSET = 0x78DBC
PATCHED_LABEL = b"MODO ONLINE?"
ORIGINAL_LABEL = b"LINKED GAME?"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recupera el SCUS retail desde el respaldo menu_only"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source = args.source.read_bytes()
    observed = sha256(source)
    if observed != MENU_ONLY_SHA256:
        raise SystemExit(
            "ERROR: respaldo inesperado; "
            f"SHA-256={observed}, esperado={MENU_ONLY_SHA256}"
        )
    if source[:8] != b"PS-X EXE":
        raise SystemExit("ERROR: el archivo no es un PS-X EXE")
    if source[MENU_OFFSET : MENU_OFFSET + len(PATCHED_LABEL)] != PATCHED_LABEL:
        raise SystemExit("ERROR: el texto menu_only no está en el offset conocido")

    recovered = bytearray(source)
    recovered[MENU_OFFSET : MENU_OFFSET + len(ORIGINAL_LABEL)] = ORIGINAL_LABEL
    recovered_hash = sha256(recovered)
    if recovered_hash != ORIGINAL_SHA256:
        raise SystemExit(
            "ERROR: la reconstrucción no coincide con el SCUS retail; "
            f"SHA-256={recovered_hash}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(recovered)
    print(f"OK: {args.output}")
    print(f"SHA-256 entrada: {observed}")
    print(f"SHA-256 salida:  {recovered_hash}")
    print(f"Cambio único: 0x{MENU_OFFSET:X} {PATCHED_LABEL!r} -> {ORIGINAL_LABEL!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
