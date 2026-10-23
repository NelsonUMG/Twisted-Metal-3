#!/usr/bin/env python3
"""Build the isolated RNG-caller diagnostic SCUS and IPS patch.

The retail/gameplay code at 0x8003A0F0 is redirected to a trampoline placed by
the diagnostic frontend in verified 16 MiB RAM at 0x80F10100. The normal v10
SCUS is never modified in place.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


EXPECTED_V10_SHA256 = (
    "31b296f58fc3d8892358f5ef27046bd3d993b001d564f0ffa0d2a9adf9cd3ae5"
)
TEXT_ADDRESS = 0x80010000
RNG_FUNCTION = 0x8003A0F0
RNG_CODECAVE = 0x80F10100
EXPECTED_WORDS = (0x3C0341C6, 0x8F820708)


def va_to_offset(address: int) -> int:
    return 0x800 + address - TEXT_ADDRESS


def j_type(opcode: int, target: int) -> int:
    return (opcode << 26) | ((target >> 2) & 0x03FFFFFF)


def write_ips(path: Path, offset: int, payload: bytes) -> None:
    if not 0 <= offset <= 0xFFFFFF:
        raise ValueError("offset IPS fuera de rango")
    if not 0 < len(payload) <= 0xFFFF:
        raise ValueError("payload IPS fuera de rango")
    record = offset.to_bytes(3, "big") + len(payload).to_bytes(2, "big") + payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PATCH" + record + b"EOF")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crea el SCUS diagnóstico que registra el caller del RNG"
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ips", type=Path)
    args = parser.parse_args()

    source = args.input.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    if digest != EXPECTED_V10_SHA256:
        raise SystemExit(
            f"ERROR: SCUS v10 inesperado: {digest}; esperado {EXPECTED_V10_SHA256}"
        )
    if source[:8] != b"PS-X EXE":
        raise SystemExit("ERROR: el archivo no es un PS-X EXE")

    offset = va_to_offset(RNG_FUNCTION)
    actual_words = struct.unpack_from("<II", source, offset)
    if actual_words != EXPECTED_WORDS:
        raise SystemExit(
            "ERROR: instrucciones RNG inesperadas en "
            f"0x{offset:X}: {[f'0x{x:08X}' for x in actual_words]}"
        )

    patch_words = (j_type(0x02, RNG_CODECAVE), 0)
    patch = struct.pack("<II", *patch_words)
    output = bytearray(source)
    output[offset : offset + len(patch)] = patch
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    if args.ips:
        write_ips(args.ips, offset, patch)

    output_digest = hashlib.sha256(output).hexdigest()
    print(f"Input:  {args.input} SHA-256={digest}")
    print(f"Patch:  offset=0x{offset:X} words={' '.join(f'0x{x:08X}' for x in patch_words)}")
    print(f"Target: 0x{RNG_CODECAVE:08X}")
    print(f"Output: {args.output} SHA-256={output_digest}")
    if args.ips:
        print(f"IPS:    {args.ips}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
