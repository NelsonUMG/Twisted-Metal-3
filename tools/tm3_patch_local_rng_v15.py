#!/usr/bin/env python3
"""Create the isolated v15 SCUS with a private RNG for role-local work.

The v10 gameplay batch remains unchanged.  Two callers proven asymmetric by
the non-intrusive Beetle trace are redirected to a private LCG in the unused
post-SIO gap:

* 0x80021E48 selects a resource for a short-lived type-0x16 visual object.
* 0x80017158 breaks ties inside a role-local path search (up to 100 nodes).
* 0x8001B738 and 0x8001B78C make two role-local weighted AI selections.

Neither caller may advance the shared gameplay RNG at gp+0x708.
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
CALL_SITES = (0x80021E48, 0x80017158, 0x8001B738, 0x8001B78C)
PRIVATE_RNG = 0x80047800
PRIVATE_STATE = 0x80047840
PRIVATE_SEED = 0xC05E71C5
EXPECTED_SHARED_RNG_JAL = 0x0C00E83C  # jal 0x8003A0F0


def va_to_offset(address: int) -> int:
    return 0x800 + address - TEXT_ADDRESS


def j_type(opcode: int, target: int) -> int:
    return (opcode << 26) | ((target >> 2) & 0x03FFFFFF)


def write_ips(path: Path, records: list[tuple[int, bytes]]) -> None:
    payload = bytearray(b"PATCH")
    for offset, data in records:
        if not 0 <= offset <= 0xFFFFFF:
            raise ValueError("offset IPS fuera de rango")
        if not 0 < len(data) <= 0xFFFF:
            raise ValueError("payload IPS fuera de rango")
        payload += offset.to_bytes(3, "big")
        payload += len(data).to_bytes(2, "big")
        payload += data
    payload += b"EOF"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Separa del RNG compartido dos callers locales verificados"
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

    call_records: list[tuple[int, bytes]] = []
    for call_site in CALL_SITES:
        call_offset = va_to_offset(call_site)
        old_call = struct.unpack_from("<I", source, call_offset)[0]
        if old_call != EXPECTED_SHARED_RNG_JAL:
            raise SystemExit(
                f"ERROR: JAL inesperado en 0x{call_site:08X}: 0x{old_call:08X}"
            )
        call_records.append(
            (call_offset, struct.pack("<I", j_type(0x03, PRIVATE_RNG)))
        )

    # This keeps the original RNG's clobber set: v0, v1, a0 and HI/LO.
    # The nop after lw is required for the R3000A load delay.
    routine_words = (
        0x3C038004,  # lui   v1,0x8004
        0x34637840,  # ori   v1,v1,0x7840
        0x8C620000,  # lw    v0,0(v1)
        0x00000000,  # nop                  ; load delay
        0x3C0341C6,  # lui   v1,0x41C6
        0x34634E6D,  # ori   v1,v1,0x4E6D
        0x00430018,  # mult  v0,v1
        0x00002012,  # mflo  a0
        0x24823039,  # addiu v0,a0,0x3039
        0x3C038004,  # lui   v1,0x8004
        0xAC627840,  # sw    v0,0x7840(v1)
        0x00021402,  # srl   v0,v0,16
        0x03E00008,  # jr    ra
        0x30427FFF,  # andi  v0,v0,0x7FFF   ; delay slot
    )
    routine = struct.pack("<" + "I" * len(routine_words), *routine_words)
    cave_offset = va_to_offset(PRIVATE_RNG)
    state_offset = va_to_offset(PRIVATE_STATE)
    if cave_offset + len(routine) > state_offset:
        raise SystemExit("ERROR: la rutina invade su estado privado")
    if any(source[cave_offset : state_offset + 4]):
        raise SystemExit(
            "ERROR: el codecave 0x80047800..0x80047843 ya contiene datos"
        )

    cave_payload = bytearray(state_offset + 4 - cave_offset)
    cave_payload[: len(routine)] = routine
    struct.pack_into("<I", cave_payload, state_offset - cave_offset, PRIVATE_SEED)
    records = call_records + [(cave_offset, bytes(cave_payload))]

    output = bytearray(source)
    for offset, data in records:
        output[offset : offset + len(data)] = data
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    if args.ips:
        write_ips(args.ips, records)

    for call_site in CALL_SITES:
        if (
            struct.unpack_from("<I", output, va_to_offset(call_site))[0]
            != j_type(0x03, PRIVATE_RNG)
        ):
            raise SystemExit(
                f"ERROR: verificación del JAL v15 falló en 0x{call_site:08X}"
            )
    if output[cave_offset : cave_offset + len(routine)] != routine:
        raise SystemExit("ERROR: verificación de la rutina v15 falló")
    if struct.unpack_from("<I", output, state_offset)[0] != PRIVATE_SEED:
        raise SystemExit("ERROR: verificación de la semilla privada falló")

    output_digest = hashlib.sha256(output).hexdigest()
    print(f"Input:   {args.input} SHA-256={digest}")
    for call_site in CALL_SITES:
        print(
            f"Call:    0x{call_site:08X} 0x{EXPECTED_SHARED_RNG_JAL:08X} -> "
            f"0x{j_type(0x03, PRIVATE_RNG):08X} (jal 0x{PRIVATE_RNG:08X})"
        )
    print(
        f"Routine: 0x{PRIVATE_RNG:08X}.."
        f"0x{PRIVATE_RNG + len(routine) - 1:08X} ({len(routine)} bytes)"
    )
    print(f"State:   0x{PRIVATE_STATE:08X}=0x{PRIVATE_SEED:08X}")
    print(f"Output:  {args.output} SHA-256={output_digest}")
    if args.ips:
        print(f"IPS:     {args.ips}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
