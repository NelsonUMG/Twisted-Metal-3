#!/usr/bin/env python3
"""Static regression checks for the isolated AI-owner v19 PS-X patch."""

from __future__ import annotations

import hashlib
import importlib.util
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PATCHER_PATH = ROOT / "tools" / "tm3_patch_ai_owner_v19.py"
SOURCE_PATH = ROOT / "TM3_EXTRAIDO" / "SCUS_942.49.rngcaller_diag_v12"
OUTPUT_PATH = ROOT / "TM3_EXTRAIDO" / "SCUS_942.49.ai_owner_v19"
IPS_PATH = ROOT / "patches" / "tm3_ai_owner_v19_from_v12.ips"


def load_patcher():
    spec = importlib.util.spec_from_file_location("tm3_ai_owner_v19", PATCHER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load v19 patcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply_ips(source: bytes, patch: bytes) -> bytes:
    assert patch.startswith(b"PATCH") and patch.endswith(b"EOF")
    output = bytearray(source)
    cursor = 5
    while patch[cursor:cursor + 3] != b"EOF":
        offset = int.from_bytes(patch[cursor:cursor + 3], "big")
        size = int.from_bytes(patch[cursor + 3:cursor + 5], "big")
        cursor += 5
        if size:
            output[offset:offset + size] = patch[cursor:cursor + size]
            cursor += size
        else:
            run_size = int.from_bytes(patch[cursor:cursor + 2], "big")
            value = patch[cursor + 2]
            cursor += 3
            output[offset:offset + run_size] = bytes([value]) * run_size
    assert cursor + 3 == len(patch)
    return bytes(output)


def instruction_reads(word: int) -> set[int]:
    opcode = word >> 26
    rs = (word >> 21) & 31
    rt = (word >> 16) & 31
    function = word & 63
    if opcode == 0:
        if function in (0x00, 0x02, 0x03):  # fixed shifts
            return {rt}
        if function == 0x08:  # jr
            return {rs}
        if function in (0x21, 0x23, 0x24, 0x25, 0x26, 0x2A, 0x2B):
            return {rs, rt}
        return set()
    if opcode in (0x04, 0x05):  # beq/bne
        return {rs, rt}
    if opcode in (0x09, 0x0B, 0x0C, 0x0D, 0x23, 0x25, 0x29):
        return {rs}
    if opcode == 0x2B:  # sw
        return {rs, rt}
    return set()


def check_load_delays(name: str, payload: bytes) -> None:
    words = list(struct.unpack(f"<{len(payload) // 4}I", payload))
    for index, word in enumerate(words[:-1]):
        if word >> 26 != 0x23:
            continue
        loaded = (word >> 16) & 31
        assert loaded not in instruction_reads(words[index + 1]), (
            f"{name}: R3000A load-delay hazard at word {index}, r{loaded}"
        )


def check_branch_targets(name: str, start: int, payload: bytes) -> None:
    words = list(struct.unpack(f"<{len(payload) // 4}I", payload))
    end = start + len(payload)
    for index, word in enumerate(words):
        if word >> 26 not in (0x04, 0x05):
            continue
        immediate = word & 0xFFFF
        if immediate & 0x8000:
            immediate -= 0x10000
        target = start + index * 4 + 4 + immediate * 4
        assert start <= target < end, f"{name}: branch escapes routine to 0x{target:08X}"


def main() -> int:
    patcher = load_patcher()
    source = SOURCE_PATH.read_bytes()
    output = OUTPUT_PATH.read_bytes()
    ips = IPS_PATH.read_bytes()
    assert hashlib.sha256(source).hexdigest() == patcher.EXPECTED_V12_SHA256
    assert apply_ips(source, ips) == output

    routines = (
        ("batch", patcher.AI_BATCH_FUNCTION, patcher.build_ai_batch()),
        ("prepass", patcher.AI_PREPASS_FUNCTION, patcher.build_ai_prepass()),
        ("apply", patcher.AI_APPLY_FUNCTION, patcher.build_ai_apply()),
        ("gate", patcher.AI_GATE_FUNCTION, patcher.build_ai_gate()),
    )
    for name, address, payload in routines:
        offset = patcher.va_to_offset(address)
        assert output[offset:offset + len(payload)] == payload
        check_load_delays(name, payload)
        check_branch_targets(name, address, payload)

    allowed = [
        (patcher.va_to_offset(patcher.GAMEPLAY_RNG_GETTER_CALL), 4),
        (patcher.va_to_offset(patcher.VEHICLE_CONTROL_CALL), 4),
        (patcher.va_to_offset(patcher.GAMEPLAY_BATCH_ENTRY), 8),
    ]
    allowed.extend((patcher.va_to_offset(address), len(payload)) for _, address, payload in routines)
    for index, (before, after) in enumerate(zip(source, output)):
        if before == after:
            continue
        assert any(offset <= index < offset + size for offset, size in allowed), (
            f"unexpected changed byte at PS-X EXE offset 0x{index:X}"
        )

    # One local human record is sent by each linked console.  The authority
    # adds 52 bytes per CPU; all supported 1H+1..7CPU and 2H+1..6CPU cases
    # remain inside one 1,200-byte UDP fragment.
    for cpu_count in range(8):
        follower_payload = 4 + 24 + 4 + patcher.SCRATCH_HEADER_SIZE
        authority_payload = follower_payload + cpu_count * patcher.CPU_RECORD_SIZE
        assert follower_payload == 48
        assert authority_payload <= 1200
        assert authority_payload <= 4 + 24 + 4 + 16 + 7 * 52

    print("OK static v19")
    print(f"source={hashlib.sha256(source).hexdigest()}")
    print(f"output={hashlib.sha256(output).hexdigest()}")
    print(f"ips={hashlib.sha256(ips).hexdigest()}")
    print("payloads: follower=48, authority=48..412, UDP fragments=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
