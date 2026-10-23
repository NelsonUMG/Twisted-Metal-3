#!/usr/bin/env python3
"""Build an isolated four-byte path-stamp experiment from the exact v12 SCUS.

Both path routines use graph-node +0x12 as a visited generation. This candidate
makes the RNG path use the destination path's gp+0x1c generation counter, so
serial calls cannot immediately reuse the other routine's generation. It does
not address 16-bit wrap, nested/reentrant searches, or unrelated divergence.
No game disc, base executable, seed, RNG call, or network field is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "TM3_EXTRAIDO" / "SCUS_942.49.rngcaller_diag_v12"
OUTPUT_DIR = ROOT / "diagnostics" / "path_stamp_v1"
OUTPUT_SCUS = OUTPUT_DIR / "SCUS_942.49.path_stamp_v1"
OUTPUT_IPS = OUTPUT_DIR / "tm3_path_stamp_v1_from_v12.ips"
SOURCE_SHA256 = "56fc9301f987a6e6f22402ae7266652c70ede09ce8c02a666828e48152c74843"
LOAD_ADDRESS = 0x80010000
SOURCE_SIZE = 655360
PATCH_WORDS = {
    0x80016F14: (0x9782001E, 0x9782001C),
    0x80016F2C: (0xA782001E, 0xA782001C),
    0x80016F38: (0x9783001E, 0x9783001C),
    0x80017190: (0x9783001E, 0x9783001C),
}
DESTINATION_COUNTER_REFS = {
    0x80016898: 0x9782001C,
    0x800168B0: 0xA782001C,
    0x800168BC: 0x9783001C,
    0x80016A6C: 0x9783001C,
}
# Verify the premise against instructions, not names assigned by decompilation.
CONTEXT_WORDS = {
    # Destination path: table 0x80089d18+0x10; (node*8-node)*4.
    0x80016838: 0x3C028009,
    0x8001683C: 0x24479D18,
    0x80016848: 0x000310C0,
    0x8001684C: 0x00431023,
    0x80016854: 0x8CE80010,
    0x80016858: 0x00021080,
    # Destination path visited tag stores and comparison read.
    0x800168C4: 0xA4430012,
    0x80016A70: 0x94820012,
    0x80016B60: 0xA4830012,
    # RNG path: identical table and stride.
    0x80016EB0: 0x3C028009,
    0x80016EB4: 0x24479D18,
    0x80016EC0: 0x000218C0,
    0x80016EC4: 0x00621823,
    0x80016EF0: 0x8CE20010,
    0x80016EF4: 0x00032080,
    # RNG path visited tag stores and comparison read.
    0x80016F40: 0xA4430012,
    0x80017194: 0x94820012,
    0x80017284: 0xA4830012,
    **DESTINATION_COUNTER_REFS,
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def offset(pc: int) -> int:
    return 0x800 + pc - LOAD_ADDRESS


def word(data: bytes, pc: int) -> int:
    return struct.unpack_from("<I", data, offset(pc))[0]


def counter_refs(data: bytes, start: int, end: int) -> dict[int, int]:
    """All gp+0x1c/0x1e operands, including unexpected opcode classes."""
    result = {}
    for pc in range(start, end, 4):
        instruction = word(data, pc)
        if (instruction >> 21) & 31 == 28 and instruction & 0xFFFF in (0x1C, 0x1E):
            result[pc] = instruction
    return result


def validate_source(data: bytes) -> None:
    actual = digest(data)
    if actual != SOURCE_SHA256:
        raise ValueError(f"Source is not the exact v12 control: SHA256={actual}")
    if len(data) != SOURCE_SIZE or data[:8] != b"PS-X EXE":
        raise ValueError("Unexpected v12 PS-X EXE header/size")
    if struct.unpack_from("<I", data, 0x18)[0] != LOAD_ADDRESS:
        raise ValueError("Unexpected PS-X EXE load address")
    expected = {**CONTEXT_WORDS, **{pc: old for pc, (old, _) in PATCH_WORDS.items()}}
    for pc, instruction in expected.items():
        if word(data, pc) != instruction:
            raise ValueError(f"Instruction premise failed at 0x{pc:08X}")
    if counter_refs(data, 0x8001682C, 0x80016D28) != DESTINATION_COUNTER_REFS:
        raise ValueError("Unexpected destination-path generation operands")
    if counter_refs(data, 0x80016EA8, 0x8001746C) != {
        pc: old for pc, (old, _) in PATCH_WORDS.items()
    }:
        raise ValueError("Unexpected RNG-path generation operands")


def replay_ips(source: bytes, patch: bytes) -> bytes:
    """Strict decoder for this candidate's non-RLE, non-extending IPS records."""
    if not patch.startswith(b"PATCH"):
        raise ValueError("Missing IPS header")
    result = bytearray(source)
    pos = 5
    while True:
        if patch[pos:pos + 3] == b"EOF":
            if pos + 3 != len(patch):
                raise ValueError("Unexpected IPS trailing bytes")
            return bytes(result)
        if pos + 5 > len(patch):
            raise ValueError("Truncated IPS record")
        start = int.from_bytes(patch[pos:pos + 3], "big")
        size = int.from_bytes(patch[pos + 3:pos + 5], "big")
        pos += 5
        if not size or pos + size > len(patch) or start + size > len(result):
            raise ValueError("Invalid or extending IPS record")
        result[start:start + size] = patch[pos:pos + size]
        pos += size


def build(source: bytes) -> tuple[bytes, bytes, dict]:
    validate_source(source)
    patched = bytearray(source)
    patch = bytearray(b"PATCH")
    changes = []
    for pc, (old, new) in PATCH_WORDS.items():
        at = offset(pc)
        struct.pack_into("<I", patched, at, new)
        # Only the low byte changes (0x1e -> 0x1c); retain all other bytes.
        patch.extend(at.to_bytes(3, "big") + b"\x00\x01\x1c")
        changes.append({"pc": f"0x{pc:08X}", "file_offset": f"0x{at:X}",
                        "old_word": f"0x{old:08X}", "new_word": f"0x{new:08X}"})
    patch.extend(b"EOF")
    result = bytes(patched)
    expected_offsets = {offset(pc) for pc in PATCH_WORDS}
    differences = {i for i, (old, new) in enumerate(zip(source, result)) if old != new}
    if len(result) != len(source) or differences != expected_offsets:
        raise ValueError("Patch changed bytes outside the four approved immediates")
    if replay_ips(source, bytes(patch)) != result:
        raise ValueError("IPS replay did not reproduce SCUS")
    for pc, instruction in CONTEXT_WORDS.items():
        if word(result, pc) != instruction:
            raise ValueError("Context instruction was changed")
    metadata = {
        "status": "experimental_unvalidated_in_game",
        "source_sha256": digest(source),
        "candidate_sha256": digest(result),
        "ips_sha256": digest(bytes(patch)),
        "size": len(result), "changed_bytes": len(differences),
        "changes": changes,
        "limitations": ["16-bit generation wrap remains", "reentrancy not addressed",
                        "live linked-game A/B required", "v12 timing shim remains"],
    }
    return result, bytes(patch), metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--verify-only", action="store_true", help="Validate entirely in memory")
    args = parser.parse_args()
    result, patch, metadata = build(args.source.read_bytes())
    outputs = ((OUTPUT_SCUS, result), (OUTPUT_IPS, patch))
    if not args.verify_only:
        # Preflight both paths; never replace an existing different experiment.
        for path, payload in outputs:
            if path.resolve() == args.source.resolve():
                raise ValueError("Output must not be the source")
            if path.exists() and path.read_bytes() != payload:
                raise FileExistsError(f"Refusing to overwrite different content: {path}")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for path, payload in outputs:
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(payload)
            if path.read_bytes() != payload:
                raise ValueError(f"Written artifact verification failed: {path}")
    metadata["wrote_artifacts"] = not args.verify_only
    metadata["scus"] = str(OUTPUT_SCUS)
    metadata["ips"] = str(OUTPUT_IPS)
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
