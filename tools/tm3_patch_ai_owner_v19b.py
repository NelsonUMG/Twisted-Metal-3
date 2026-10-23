#!/usr/bin/env python3
"""Build the isolated TM3 AI-owner v19b PS-X executable and high-RAM code.

This patch is intentionally based on RNGCaller v12, never on the clean v10
SCUS.  It keeps the v12 RNG timing shim and moves linked-game CPU control to a
single owner (role 2):

* role 2 evaluates CPU AI once every two synchronized game ticks before the
  gameplay batch and reuses the generated controls on the intervening tick;
* one compact record per CPU (roster + 48 bytes of generated controls/events)
  travels in the existing four-range BATCH_TRANSFER mailbox;
* role 1 validates and applies those records before the world update;
* both roles skip the duplicate CPU-control callback during the normal vehicle
  update, while human callbacks remain untouched;
* the original RANDOM SYNC comparison is preserved as a pre-AI boundary check.
  Role 1 adopts the authority's post-AI seed only after the pre-AI seeds have
  been exchanged, so the comparison does not silently hide an earlier world
  divergence as v17 did.

The first v19 experiment wrote routines into a zero-filled EXE interval that
had not been proven dead and produced a black screen before the intro.  v19b
keeps only three hooks in the SCUS and has the frontend install all routines in
expanded RAM before the first emulated frame, matching the proven v12 codecave
deployment model.  No input file is ever modified in place.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


EXPECTED_V12_SHA256 = "56fc9301f987a6e6f22402ae7266652c70ede09ce8c02a666828e48152c74843"

TEXT_ADDRESS = 0x80010000
GAMEPLAY_RNG_GETTER_CALL = 0x8003AA7C
VEHICLE_CONTROL_CALL = 0x8001834C
GAMEPLAY_BATCH_ENTRY = 0x80047A00

# Code is installed by the v19b frontend at RAM offsets 0xE10000..0xE10FFF.
# v12 uses 0xF00000..0xF1013B, so the two diagnostic regions do not overlap.
AI_BATCH_FUNCTION = 0x80E10000
AI_PREPASS_FUNCTION = 0x80E10400
AI_APPLY_FUNCTION = 0x80E10600
AI_GATE_FUNCTION = 0x80E10800
CODE_CAVE_END = 0x80E11000
AI_CODE_RAM_OFFSET = AI_BATCH_FUNCTION & 0x00FFFFFF

ORIGINAL_CONTROL_FUNCTION = 0x8001A390
MAILBOX_ADDRESS = 0x80047900
MAILBOX_MAGIC = 0x4F334D54  # bytes: TM3O
MAILBOX_VERSION = 5
MAILBOX_COMMAND_BATCH_TRANSFER = 3

SCRATCH_ADDRESS = 0x80E00000
SCRATCH_MAGIC = 0x42393141  # bytes: A19B
SCRATCH_HEADER_SIZE = 16
CPU_RECORD_SIZE = 52
MAX_CPU_VEHICLES = 7
AI_UPDATE_MASK = 1  # evaluate on even synchronized game-time ticks (30 -> 15 Hz)

REGISTERED_VEHICLES = 0x800D3234
HUMAN_VEHICLES = 0x800D323C
VEHICLE_POINTERS = 0x800D3240
GAME_ROLE = 0x800D3298
REMOTE_HUMAN_COUNT = 0x800D2CB4
RNG_SEED = 0x80089BC8

EXPECTED_WORDS = {
    GAMEPLAY_RNG_GETTER_CALL: 0x0C00E849,  # jal 0x8003A124
    VEHICLE_CONTROL_CALL: 0x0C0068E4,     # jal 0x8001A390
    GAMEPLAY_BATCH_ENTRY: 0x3C088004,     # lui t0,0x8004
    GAMEPLAY_BATCH_ENTRY + 4: 0x35087900, # ori t0,t0,0x7900
}

REG = {
    "zero": 0, "at": 1, "v0": 2, "v1": 3,
    "a0": 4, "a1": 5, "a2": 6, "a3": 7,
    "t0": 8, "t1": 9, "t2": 10, "t3": 11,
    "t4": 12, "t5": 13, "t6": 14, "t7": 15,
    "s0": 16, "s1": 17, "s2": 18, "s3": 19,
    "s4": 20, "s5": 21, "s6": 22, "s7": 23,
    "t8": 24, "t9": 25, "gp": 28, "sp": 29,
    "fp": 30, "ra": 31,
}


def r_type(rs: int, rt: int, rd: int, shift: int, function: int) -> int:
    return (rs << 21) | (rt << 16) | (rd << 11) | (shift << 6) | function


def i_type(opcode: int, rs: int, rt: int, immediate: int) -> int:
    return (opcode << 26) | (rs << 21) | (rt << 16) | (immediate & 0xFFFF)


def j_type(opcode: int, target: int) -> int:
    return (opcode << 26) | ((target >> 2) & 0x03FFFFFF)


class Assembler:
    def __init__(self, address: int):
        self.address = address
        self.words: list[int] = []
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, int, int, int, str]] = []

    def emit(self, word: int) -> None:
        self.words.append(word)

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate label: {name}")
        self.labels[name] = self.address + len(self.words) * 4

    def branch(self, opcode: int, rs: int, rt: int, label: str) -> None:
        index = len(self.words)
        self.fixups.append((index, opcode, rs, rt, label))
        self.emit(0)

    def jump(self, target: int, link: bool = False) -> None:
        self.emit(j_type(0x03 if link else 0x02, target))

    def resolve(self) -> bytes:
        for index, opcode, rs, rt, label in self.fixups:
            target = self.labels[label]
            source = self.address + index * 4
            delta = target - (source + 4)
            if delta % 4:
                raise ValueError(f"unaligned branch to {label}")
            immediate = delta // 4
            if not -0x8000 <= immediate <= 0x7FFF:
                raise ValueError(f"branch out of range to {label}")
            self.words[index] = i_type(opcode, rs, rt, immediate)
        return b"".join(struct.pack("<I", word) for word in self.words)


def move(rd: int, rs: int) -> int:
    return r_type(rs, REG["zero"], rd, 0, 0x21)


def build_ai_prepass() -> bytes:
    """Role 2 evaluates CPU AI and packs generated controls into high RAM."""
    z, v0 = REG["zero"], REG["v0"]
    a0 = REG["a0"]
    t0, t1, t2, t3, t4 = (REG[n] for n in ("t0", "t1", "t2", "t3", "t4"))
    s0, s1, s2, s3, s4, s5, s6 = (REG[n] for n in ("s0", "s1", "s2", "s3", "s4", "s5", "s6"))
    gp, sp, ra = REG["gp"], REG["sp"], REG["ra"]
    asm = Assembler(AI_PREPASS_FUNCTION)

    asm.emit(i_type(0x09, sp, sp, -0x30))
    for reg, offset in ((ra, 0x2C), (s0, 0x28), (s1, 0x24), (s2, 0x20),
                        (s3, 0x1C), (s4, 0x18), (s5, 0x14), (s6, 0x10)):
        asm.emit(i_type(0x2B, sp, reg, offset))

    asm.emit(i_type(0x0F, z, s4, SCRATCH_ADDRESS >> 16))
    asm.emit(i_type(0x0F, z, t0, 0x8009))
    asm.emit(i_type(0x23, t0, s3, RNG_SEED - 0x80090000))
    asm.emit(0)  # load delay
    asm.emit(i_type(0x2B, s4, s3, 0))       # pre-AI seed
    asm.emit(i_type(0x2B, s4, s3, 4))       # post-AI defaults to pre-AI
    asm.emit(i_type(0x2B, s4, z, 8))        # no records until fully packed
    asm.emit(i_type(0x0F, z, t1, SCRATCH_MAGIC >> 16))
    asm.emit(i_type(0x0D, t1, t1, SCRATCH_MAGIC & 0xFFFF))
    asm.emit(i_type(0x2B, s4, t1, 12))

    asm.emit(i_type(0x0F, z, t0, 0x800D))
    asm.emit(i_type(0x23, t0, t1, GAME_ROLE - 0x800D0000))
    asm.emit(0)
    asm.emit(i_type(0x09, z, t2, 2))
    asm.branch(0x05, t1, t2, "finish")     # only role 2 owns CPU AI
    asm.emit(0)

    asm.emit(i_type(0x23, t0, s1, HUMAN_VEHICLES - 0x800D0000))
    asm.emit(i_type(0x23, t0, s2, REGISTERED_VEHICLES - 0x800D0000))
    asm.emit(0)
    asm.emit(r_type(s2, s1, t1, 0, 0x23))   # registered - humans
    asm.emit(i_type(0x0B, t1, t2, MAX_CPU_VEHICLES + 1))
    asm.branch(0x04, t2, z, "finish")
    asm.emit(0)
    asm.emit(r_type(s1, s2, t1, 0, 0x2A))   # humans < registered
    asm.branch(0x04, t1, z, "authority_done")
    asm.emit(0)

    asm.emit(i_type(0x09, t0, s0, VEHICLE_POINTERS - 0x800D0000))
    asm.emit(r_type(z, s1, t1, 2, 0x00))
    asm.emit(r_type(s0, t1, s0, 0, 0x21))
    asm.emit(i_type(0x09, s4, s5, SCRATCH_HEADER_SIZE))
    asm.emit(move(s6, z))
    # The game-time word was exchanged immediately before this hook.  Both
    # peers therefore make the same throttle decision.  The authority still
    # packs the currently held controls every tick, so the follower never has
    # to infer or extrapolate them.
    asm.emit(i_type(0x23, gp, t1, 0x00E8))
    asm.emit(0)
    asm.emit(i_type(0x0C, t1, t1, AI_UPDATE_MASK))
    asm.emit(i_type(0x2B, sp, t1, 0x0C))

    asm.label("vehicle_loop")
    asm.emit(i_type(0x23, s0, s3, 0))
    asm.emit(0)
    asm.branch(0x04, s3, z, "authority_done")
    asm.emit(0)
    asm.emit(i_type(0x23, sp, t1, 0x0C))
    asm.emit(0)
    asm.branch(0x05, t1, z, "pack_controls")
    asm.emit(0)
    asm.jump(ORIGINAL_CONTROL_FUNCTION, link=True)
    asm.emit(move(a0, s3))

    asm.label("pack_controls")
    asm.emit(i_type(0x23, s3, t1, 0x0F50))
    asm.emit(0)
    asm.emit(i_type(0x2B, s5, t1, 0))
    asm.emit(i_type(0x09, s3, t1, 0x0F58))
    asm.emit(i_type(0x09, s5, t2, 4))
    asm.emit(i_type(0x09, z, t3, 11))
    asm.label("copy_controls")
    asm.emit(i_type(0x23, t1, t4, 0))
    asm.emit(i_type(0x09, t1, t1, 4))      # load-delay filler
    asm.emit(i_type(0x2B, t2, t4, 0))
    asm.emit(i_type(0x09, t2, t2, 4))
    asm.emit(i_type(0x09, t3, t3, -1))
    asm.branch(0x05, t3, z, "copy_controls")
    asm.emit(0)
    asm.emit(i_type(0x23, s3, t4, 0x0F9C))
    asm.emit(0)
    asm.emit(i_type(0x2B, s5, t4, 48))

    asm.emit(i_type(0x09, s5, s5, CPU_RECORD_SIZE))
    asm.emit(i_type(0x09, s6, s6, 1))
    asm.emit(i_type(0x09, s0, s0, 4))
    asm.emit(i_type(0x09, s1, s1, 1))
    asm.emit(r_type(s1, s2, t1, 0, 0x2A))
    asm.branch(0x05, t1, z, "vehicle_loop")
    asm.emit(0)

    asm.label("authority_done")
    asm.emit(i_type(0x2B, s4, s6, 8))
    asm.emit(i_type(0x0F, z, t0, 0x8009))
    asm.emit(i_type(0x23, t0, t1, RNG_SEED - 0x80090000))
    asm.emit(0)
    asm.emit(i_type(0x2B, s4, t1, 4))       # post-AI seed

    asm.label("finish")
    # s3 is reused as the current vehicle pointer inside the authority loop.
    # Reload the immutable boundary seed from the scratch header instead of
    # accidentally returning the last processed vehicle pointer.
    asm.emit(i_type(0x23, s4, v0, 0))        # return pre-AI seed
    for reg, offset in ((ra, 0x2C), (s0, 0x28), (s1, 0x24), (s2, 0x20),
                        (s3, 0x1C), (s4, 0x18), (s5, 0x14), (s6, 0x10)):
        asm.emit(i_type(0x23, sp, reg, offset))
    asm.emit(r_type(ra, z, z, 0, 0x08))
    asm.emit(i_type(0x09, sp, sp, 0x30))
    return asm.resolve()


def build_ai_apply() -> bytes:
    """Validate all role-2 records, then apply controls on role 1."""
    z, v0, v1 = REG["zero"], REG["v0"], REG["v1"]
    a0, a1, a2, a3 = (REG[n] for n in ("a0", "a1", "a2", "a3"))
    t0, t1, t2, t3, t4, t5, t6, t7, t8, t9 = (
        REG[n] for n in ("t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9")
    )
    ra = REG["ra"]
    asm = Assembler(AI_APPLY_FUNCTION)

    asm.emit(i_type(0x0F, z, t0, SCRATCH_ADDRESS >> 16))
    asm.emit(i_type(0x23, t0, t1, 8))
    asm.emit(i_type(0x23, t0, t2, 12))
    asm.emit(i_type(0x0F, z, t3, SCRATCH_MAGIC >> 16))
    asm.emit(i_type(0x0D, t3, t3, SCRATCH_MAGIC & 0xFFFF))
    asm.branch(0x05, t2, t3, "failure")
    asm.emit(0)
    asm.emit(i_type(0x0B, t1, t2, MAX_CPU_VEHICLES + 1))
    asm.branch(0x04, t2, z, "failure")
    asm.emit(0)

    asm.emit(i_type(0x0F, z, t3, 0x800D))
    asm.emit(i_type(0x23, t3, t4, REGISTERED_VEHICLES - 0x800D0000))
    asm.emit(i_type(0x23, t3, t5, HUMAN_VEHICLES - 0x800D0000))
    asm.emit(0)
    asm.emit(r_type(t4, t5, t6, 0, 0x23))
    asm.branch(0x05, t1, t6, "failure")
    asm.emit(0)

    # Validation pass: no game state is touched until every record maps to the
    # same roster entry in the receiver's local pointer table.
    asm.emit(i_type(0x09, t3, a0, VEHICLE_POINTERS - 0x800D0000))
    asm.emit(r_type(z, t5, t7, 2, 0x00))
    asm.emit(r_type(a0, t7, a0, 0, 0x21))
    asm.emit(i_type(0x09, t0, a1, SCRATCH_HEADER_SIZE))
    asm.emit(move(a2, t1))
    asm.branch(0x04, a2, z, "validated")
    asm.emit(0)
    asm.label("validate_loop")
    asm.emit(i_type(0x23, a0, t8, 0))
    asm.emit(i_type(0x23, a1, t9, 0))
    asm.branch(0x04, t8, z, "failure")
    asm.emit(0)
    asm.emit(i_type(0x23, t8, v1, 0x0F50))
    asm.emit(0)
    asm.branch(0x05, v1, t9, "failure")
    asm.emit(0)
    asm.emit(i_type(0x09, a0, a0, 4))
    asm.emit(i_type(0x09, a1, a1, CPU_RECORD_SIZE))
    asm.emit(i_type(0x09, a2, a2, -1))
    asm.branch(0x05, a2, z, "validate_loop")
    asm.emit(0)

    asm.label("validated")
    asm.emit(i_type(0x09, t3, a0, VEHICLE_POINTERS - 0x800D0000))
    asm.emit(r_type(z, t5, t7, 2, 0x00))
    asm.emit(r_type(a0, t7, a0, 0, 0x21))
    asm.emit(i_type(0x09, t0, a1, SCRATCH_HEADER_SIZE))
    asm.emit(move(a2, t1))
    asm.branch(0x04, a2, z, "success")
    asm.emit(0)
    asm.label("apply_loop")
    asm.emit(i_type(0x23, a0, t8, 0))
    asm.emit(i_type(0x09, a1, t9, 4))
    asm.emit(i_type(0x09, t8, t7, 0x0F58))
    asm.emit(i_type(0x09, z, a3, 11))
    asm.label("copy_loop")
    asm.emit(i_type(0x23, t9, v1, 0))
    asm.emit(i_type(0x09, t9, t9, 4))      # load-delay filler
    asm.emit(i_type(0x2B, t7, v1, 0))
    asm.emit(i_type(0x09, t7, t7, 4))
    asm.emit(i_type(0x09, a3, a3, -1))
    asm.branch(0x05, a3, z, "copy_loop")
    asm.emit(0)
    asm.emit(i_type(0x23, a1, v1, 48))
    asm.emit(0)
    asm.emit(i_type(0x2B, t8, v1, 0x0F9C))
    asm.emit(i_type(0x09, a0, a0, 4))
    asm.emit(i_type(0x09, a1, a1, CPU_RECORD_SIZE))
    asm.emit(i_type(0x09, a2, a2, -1))
    asm.branch(0x05, a2, z, "apply_loop")
    asm.emit(0)

    asm.label("success")
    asm.emit(i_type(0x09, z, v0, 1))
    asm.emit(r_type(ra, z, z, 0, 0x08))
    asm.emit(0)
    asm.label("failure")
    asm.emit(move(v0, z))
    asm.emit(r_type(ra, z, z, 0, 0x08))
    asm.emit(0)
    return asm.resolve()


def build_ai_gate() -> bytes:
    """Skip duplicate CPU control callbacks online; preserve human/offline flow."""
    z = REG["zero"]
    a0 = REG["a0"]
    t0, t1, t2, t3 = (REG[n] for n in ("t0", "t1", "t2", "t3"))
    ra = REG["ra"]
    asm = Assembler(AI_GATE_FUNCTION)

    asm.emit(i_type(0x0F, z, t0, 0x800D))
    asm.emit(i_type(0x23, t0, t1, REMOTE_HUMAN_COUNT - 0x800D0000))
    asm.emit(0)
    asm.branch(0x04, t1, z, "original")
    asm.emit(0)
    asm.emit(i_type(0x23, a0, t1, 0x0F50))
    asm.emit(i_type(0x23, t0, t2, HUMAN_VEHICLES - 0x800D0000))
    asm.emit(0)
    asm.emit(r_type(t1, t2, t3, 0, 0x2B))
    asm.branch(0x05, t3, z, "original")
    asm.emit(0)
    asm.emit(r_type(ra, z, z, 0, 0x08))
    asm.emit(0)
    asm.label("original")
    asm.jump(ORIGINAL_CONTROL_FUNCTION)
    asm.emit(0)
    return asm.resolve()


def build_ai_batch() -> bytes:
    """One-datagram gameplay batch with asymmetric compact CPU control state."""
    z, v0, v1 = REG["zero"], REG["v0"], REG["v1"]
    t0, t1, t2, t3, t4, t5, t6, t7, t8, t9 = (
        REG[n] for n in ("t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9")
    )
    s0, s4, s6, gp, sp, ra = (REG[n] for n in ("s0", "s4", "s6", "gp", "sp", "ra"))
    asm = Assembler(AI_BATCH_FUNCTION)

    asm.emit(i_type(0x09, sp, sp, -0x20))
    asm.emit(i_type(0x2B, sp, ra, 0x1C))
    asm.emit(i_type(0x0F, z, t0, MAILBOX_ADDRESS >> 16))
    asm.emit(i_type(0x0D, t0, t0, MAILBOX_ADDRESS & 0xFFFF))

    # Original human records remain byte-for-byte compatible.
    asm.emit(i_type(0x23, s0, t1, -0x8C))
    asm.emit(0)
    asm.emit(i_type(0x0B, t1, t9, 5))
    asm.branch(0x04, t9, z, "failure")
    asm.emit(0)
    asm.emit(r_type(z, t1, t2, 4, 0x00))
    asm.emit(r_type(z, t1, t9, 3, 0x00))
    asm.emit(r_type(t2, t9, t2, 0, 0x21))
    asm.emit(i_type(0x23, s4, t3, 4))
    asm.emit(0)
    asm.emit(i_type(0x0B, t3, t9, 5))
    asm.branch(0x04, t9, z, "failure")
    asm.emit(0)
    asm.emit(r_type(z, t3, t9, 4, 0x00))
    asm.emit(r_type(z, t3, t3, 3, 0x00))
    asm.emit(r_type(t3, t9, t3, 0, 0x21))

    # Compute authority record size = 16 + 52 * (registered - humans).
    asm.emit(i_type(0x0F, z, t6, 0x800D))
    asm.emit(i_type(0x23, t6, t7, REGISTERED_VEHICLES - 0x800D0000))
    asm.emit(i_type(0x23, t6, t8, HUMAN_VEHICLES - 0x800D0000))
    asm.emit(0)
    asm.emit(r_type(t7, t8, t7, 0, 0x23))
    asm.emit(i_type(0x0B, t7, t9, MAX_CPU_VEHICLES + 1))
    asm.branch(0x04, t9, z, "failure")
    asm.emit(0)
    asm.emit(r_type(z, t7, t8, 5, 0x00))
    asm.emit(r_type(z, t7, t9, 4, 0x00))
    asm.emit(r_type(t8, t9, t8, 0, 0x21))
    asm.emit(r_type(z, t7, t9, 2, 0x00))
    asm.emit(r_type(t8, t9, t8, 0, 0x21))
    asm.emit(i_type(0x09, t8, t8, SCRATCH_HEADER_SIZE))

    # Validate the local scratch before publishing any mailbox request.
    asm.emit(i_type(0x0F, z, t6, SCRATCH_ADDRESS >> 16))
    asm.emit(i_type(0x23, t6, t9, 12))
    asm.emit(i_type(0x0F, z, v0, SCRATCH_MAGIC >> 16))
    asm.emit(i_type(0x0D, v0, v0, SCRATCH_MAGIC & 0xFFFF))
    asm.branch(0x05, t9, v0, "failure")
    asm.emit(0)
    asm.emit(i_type(0x23, t6, t9, 8))
    asm.emit(i_type(0x0F, z, v1, 0x800D))
    asm.emit(i_type(0x23, v1, v1, GAME_ROLE - 0x800D0000))
    asm.emit(0)
    asm.emit(i_type(0x2B, sp, v1, 0x18))
    asm.emit(i_type(0x09, z, v0, 2))
    asm.branch(0x05, v1, v0, "role1")
    asm.emit(0)
    asm.branch(0x05, t9, t7, "failure")
    asm.emit(0)
    asm.emit(i_type(0x09, z, t9, SCRATCH_HEADER_SIZE))  # role2 recv header only
    asm.jump(AI_BATCH_FUNCTION)  # fixed up below to local sizes_ready label
    local_jump_index = len(asm.words) - 1
    asm.emit(0)

    asm.label("role1")
    asm.emit(i_type(0x09, z, v0, 1))
    asm.branch(0x05, v1, v0, "failure")
    asm.emit(0)
    asm.branch(0x05, t9, z, "failure")
    asm.emit(0)
    asm.emit(move(t9, t8))
    asm.emit(i_type(0x09, z, t8, SCRATCH_HEADER_SIZE))

    asm.label("sizes_ready")
    asm.words[local_jump_index] = j_type(0x02, asm.labels["sizes_ready"])
    asm.emit(i_type(0x09, t2, t4, 8))
    asm.emit(r_type(t4, t8, t4, 0, 0x21))
    asm.emit(i_type(0x09, t3, t5, 8))
    asm.emit(r_type(t5, t9, t5, 0, 0x21))

    # Mailbox v5 header and the same four descriptor pairs used by v10.
    asm.emit(i_type(0x0F, z, t7, MAILBOX_MAGIC >> 16))
    asm.emit(i_type(0x0D, t7, t7, MAILBOX_MAGIC & 0xFFFF))
    asm.emit(i_type(0x2B, t0, t7, 0))
    asm.emit(i_type(0x09, z, t7, MAILBOX_VERSION))
    asm.emit(i_type(0x29, t0, t7, 4))
    asm.emit(i_type(0x09, z, t7, MAILBOX_COMMAND_BATCH_TRANSFER))
    asm.emit(i_type(0x29, t0, t7, 8))
    asm.emit(i_type(0x2B, t0, z, 12))
    asm.emit(i_type(0x2B, t0, t4, 16))
    asm.emit(i_type(0x2B, t0, t5, 20))
    asm.emit(i_type(0x2B, t0, z, 24))
    asm.emit(i_type(0x23, sp, t6, 0x1C))
    asm.emit(0)
    asm.emit(i_type(0x2B, t0, t6, 28))
    asm.emit(i_type(0x2B, t0, z, 32))
    asm.emit(i_type(0x2B, t0, z, 36))
    asm.emit(i_type(0x09, z, t7, 4))
    asm.emit(i_type(0x2B, t0, t7, 40))
    asm.emit(i_type(0x2B, t0, t7, 44))

    asm.emit(i_type(0x2B, t0, s0, 48))
    asm.emit(i_type(0x2B, t0, t7, 52))
    asm.emit(i_type(0x2B, t0, s6, 56))
    asm.emit(i_type(0x2B, t0, t2, 60))
    asm.emit(i_type(0x09, sp, t6, 0x20 + 0xAC))
    asm.emit(i_type(0x2B, t0, t6, 64))
    asm.emit(i_type(0x2B, t0, t7, 68))
    asm.emit(i_type(0x0F, z, t6, SCRATCH_ADDRESS >> 16))
    asm.emit(i_type(0x2B, t0, t6, 72))
    asm.emit(i_type(0x2B, t0, t8, 76))

    asm.emit(i_type(0x09, sp, t6, 0x20 + 0xA8))
    asm.emit(i_type(0x2B, t0, t6, 80))
    asm.emit(i_type(0x2B, t0, t7, 84))
    asm.emit(r_type(s6, t2, t6, 0, 0x21))
    asm.emit(i_type(0x2B, t0, t6, 88))
    asm.emit(i_type(0x2B, t0, t3, 92))
    asm.emit(i_type(0x09, sp, t6, 0x20 + 0xB0))
    asm.emit(i_type(0x2B, t0, t6, 96))
    asm.emit(i_type(0x2B, t0, t7, 100))
    asm.emit(i_type(0x0F, z, t6, SCRATCH_ADDRESS >> 16))
    asm.emit(i_type(0x2B, t0, t6, 104))
    asm.emit(i_type(0x2B, t0, t9, 108))

    asm.emit(i_type(0x09, z, t7, 1))
    asm.emit(i_type(0x29, t0, t7, 6))
    asm.emit(i_type(0x09, z, t7, 3))
    asm.emit(i_type(0x09, z, t9, 4))
    asm.label("wait_loop")
    asm.emit(i_type(0x25, t0, t8, 6))
    asm.emit(0)
    asm.branch(0x04, t8, t7, "response_ready")
    asm.emit(0)
    asm.branch(0x04, t8, t9, "failure")
    asm.emit(0)
    asm.branch(0x04, z, z, "wait_loop")
    asm.emit(0)

    asm.label("response_ready")
    asm.emit(i_type(0x23, t0, t8, 24))
    asm.emit(0)
    asm.branch(0x05, t8, t5, "failure")
    asm.emit(0)
    asm.emit(i_type(0x23, sp, v1, 0x18))
    asm.emit(0)
    asm.emit(i_type(0x09, z, v0, 1))
    asm.branch(0x04, v1, v0, "apply_role1")
    asm.emit(0)

    # Role 2 receives only the follower's pre-AI boundary header.
    asm.emit(i_type(0x0F, z, t0, SCRATCH_ADDRESS >> 16))
    asm.emit(i_type(0x23, t0, t1, 8))
    asm.emit(i_type(0x23, t0, t2, 12))
    asm.emit(i_type(0x0F, z, t3, SCRATCH_MAGIC >> 16))
    asm.emit(i_type(0x0D, t3, t3, SCRATCH_MAGIC & 0xFFFF))
    asm.branch(0x05, t1, z, "failure")
    asm.emit(0)
    asm.branch(0x05, t2, t3, "failure")
    asm.emit(0)
    asm.emit(i_type(0x23, t0, t1, 0))
    asm.emit(i_type(0x09, sp, t6, 0x20))
    asm.emit(0)
    asm.emit(i_type(0x2B, t6, t1, 0xB8))   # peer pre-AI seed
    asm.branch(0x04, z, z, "success")
    asm.emit(0)

    asm.label("apply_role1")
    asm.jump(AI_APPLY_FUNCTION, link=True)
    asm.emit(0)
    asm.branch(0x04, v0, z, "failure")
    asm.emit(0)
    asm.emit(i_type(0x0F, z, t0, SCRATCH_ADDRESS >> 16))
    asm.emit(i_type(0x23, t0, t1, 0))       # authority pre-AI seed
    asm.emit(i_type(0x23, t0, t2, 4))       # authority post-AI seed
    asm.emit(i_type(0x09, sp, t6, 0x20))
    asm.emit(i_type(0x2B, t6, t1, 0xB8))
    asm.emit(i_type(0x2B, gp, t2, 0x708))   # adopt seed after boundary check data captured

    asm.label("success")
    asm.emit(i_type(0x0F, z, t0, MAILBOX_ADDRESS >> 16))
    asm.emit(i_type(0x0D, t0, t0, MAILBOX_ADDRESS & 0xFFFF))
    asm.emit(i_type(0x29, t0, z, 6))
    asm.emit(i_type(0x23, sp, ra, 0x1C))
    asm.emit(i_type(0x09, z, v0, 1))
    asm.emit(i_type(0x09, sp, sp, 0x20))
    asm.emit(r_type(ra, z, z, 0, 0x08))
    asm.emit(0)

    asm.label("failure")
    asm.emit(i_type(0x0F, z, t0, MAILBOX_ADDRESS >> 16))
    asm.emit(i_type(0x0D, t0, t0, MAILBOX_ADDRESS & 0xFFFF))
    asm.emit(i_type(0x29, t0, z, 6))
    asm.emit(i_type(0x23, sp, ra, 0x1C))
    asm.emit(move(v0, z))
    asm.emit(i_type(0x09, sp, sp, 0x20))
    asm.emit(r_type(ra, z, z, 0, 0x08))
    asm.emit(0)
    return asm.resolve()


def va_to_offset(address: int) -> int:
    return 0x800 + address - TEXT_ADDRESS


def create_ips(source: bytes, patched: bytes) -> bytes:
    if len(source) != len(patched):
        raise ValueError("IPS source and output sizes differ")
    records: list[tuple[int, bytes]] = []
    index = 0
    while index < len(source):
        if source[index] == patched[index]:
            index += 1
            continue
        start = index
        payload = bytearray()
        while index < len(source) and source[index] != patched[index] and len(payload) < 0xFFFF:
            payload.append(patched[index])
            index += 1
        records.append((start, bytes(payload)))
    output = bytearray(b"PATCH")
    for offset, payload in records:
        if offset > 0xFFFFFF:
            raise ValueError("IPS offset out of range")
        output.extend(offset.to_bytes(3, "big"))
        output.extend(len(payload).to_bytes(2, "big"))
        output.extend(payload)
    output.extend(b"EOF")
    return bytes(output)


def patch_region(output: bytearray, address: int, payload: bytes) -> None:
    offset = va_to_offset(address)
    output[offset:offset + len(payload)] = payload


def create_highram_blob(routines: tuple[tuple[str, int, bytes, int], ...]) -> bytes:
    used_end = max(address + len(payload) for _, address, payload, _ in routines)
    blob_size = (used_end - AI_BATCH_FUNCTION + 15) & ~15
    blob = bytearray(blob_size)
    for _, address, payload, _ in routines:
        offset = address - AI_BATCH_FUNCTION
        blob[offset:offset + len(payload)] = payload
    return bytes(blob)


def create_cpp_header(blob: bytes) -> str:
    if len(blob) % 4:
        raise ValueError("high-RAM blob must be word aligned")
    words = struct.unpack(f"<{len(blob) // 4}I", blob)
    lines = [
        "#pragma once",
        "#include <array>",
        "#include <cstddef>",
        "#include <cstdint>",
        "",
        "namespace tm3::ai_owner_v19b {",
        f"inline constexpr std::size_t kRamOffset = 0x{AI_CODE_RAM_OFFSET:X};",
        f"inline constexpr std::array<std::uint32_t,{len(words)}> kWords{{{{",
    ]
    for index in range(0, len(words), 6):
        group = ", ".join(f"0x{word:08X}u" for word in words[index:index + 6])
        lines.append(f"    {group},")
    lines.extend(("}};", "}", ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Crea SCUS y código high-RAM AI-owner v19b desde RNGCaller v12")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ips", type=Path)
    parser.add_argument("--highram-blob", type=Path, required=True)
    parser.add_argument("--cpp-header", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_bytes()
    if source[:8] != b"PS-X EXE":
        raise SystemExit("ERROR: input is not a PS-X EXE")
    digest = hashlib.sha256(source).hexdigest()
    if digest != EXPECTED_V12_SHA256:
        raise SystemExit(f"ERROR: unexpected v12 SHA-256 {digest}")

    for address, expected in EXPECTED_WORDS.items():
        actual = struct.unpack_from("<I", source, va_to_offset(address))[0]
        if actual != expected:
            raise SystemExit(
                f"ERROR: unexpected word at 0x{address:08X}: 0x{actual:08X}, expected 0x{expected:08X}"
            )

    batch = build_ai_batch()
    prepass = build_ai_prepass()
    apply = build_ai_apply()
    gate = build_ai_gate()
    limits = (
        ("batch", AI_BATCH_FUNCTION, batch, AI_PREPASS_FUNCTION),
        ("prepass", AI_PREPASS_FUNCTION, prepass, AI_APPLY_FUNCTION),
        ("apply", AI_APPLY_FUNCTION, apply, AI_GATE_FUNCTION),
        ("gate", AI_GATE_FUNCTION, gate, CODE_CAVE_END),
    )
    for name, address, payload, end in limits:
        if address + len(payload) > end:
            raise SystemExit(f"ERROR: {name} exceeds reserved range by {address + len(payload) - end} bytes")

    output = bytearray(source)
    patch_region(output, GAMEPLAY_RNG_GETTER_CALL, struct.pack("<I", j_type(0x03, AI_PREPASS_FUNCTION)))
    patch_region(output, VEHICLE_CONTROL_CALL, struct.pack("<I", j_type(0x03, AI_GATE_FUNCTION)))
    trampoline = struct.pack("<II", j_type(0x02, AI_BATCH_FUNCTION), 0)
    patch_region(output, GAMEPLAY_BATCH_ENTRY, trampoline)
    highram_blob = create_highram_blob(limits)

    # Postconditions that catch accidental target/address drift.
    assert struct.unpack_from("<I", output, va_to_offset(GAMEPLAY_RNG_GETTER_CALL))[0] == j_type(0x03, AI_PREPASS_FUNCTION)
    assert struct.unpack_from("<I", output, va_to_offset(VEHICLE_CONTROL_CALL))[0] == j_type(0x03, AI_GATE_FUNCTION)
    assert output[va_to_offset(GAMEPLAY_BATCH_ENTRY):va_to_offset(GAMEPLAY_BATCH_ENTRY) + 8] == trampoline
    assert output[va_to_offset(0x8003AA80):va_to_offset(0x8003AA90)] == source[va_to_offset(0x8003AA80):va_to_offset(0x8003AA90)]
    assert output[va_to_offset(0x8003AB28):va_to_offset(0x8003AC10)] == source[va_to_offset(0x8003AB28):va_to_offset(0x8003AC10)]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    if args.ips:
        args.ips.parent.mkdir(parents=True, exist_ok=True)
        args.ips.write_bytes(create_ips(source, output))
    args.highram_blob.parent.mkdir(parents=True, exist_ok=True)
    args.highram_blob.write_bytes(highram_blob)
    args.cpp_header.parent.mkdir(parents=True, exist_ok=True)
    args.cpp_header.write_text(create_cpp_header(highram_blob), encoding="utf-8")

    after = hashlib.sha256(output).hexdigest()
    max_payload = 4 + 24 + 4 + SCRATCH_HEADER_SIZE + MAX_CPU_VEHICLES * CPU_RECORD_SIZE
    print(f"OK: {args.output}")
    print(f"SHA-256 input:  {digest}")
    print(f"SHA-256 output: {after}")
    print(f"Batch:   0x{AI_BATCH_FUNCTION:08X}-0x{AI_BATCH_FUNCTION + len(batch):08X} ({len(batch)} bytes)")
    print(f"Prepass: 0x{AI_PREPASS_FUNCTION:08X}-0x{AI_PREPASS_FUNCTION + len(prepass):08X} ({len(prepass)} bytes)")
    print(f"Apply:   0x{AI_APPLY_FUNCTION:08X}-0x{AI_APPLY_FUNCTION + len(apply):08X} ({len(apply)} bytes)")
    print(f"Gate:    0x{AI_GATE_FUNCTION:08X}-0x{AI_GATE_FUNCTION + len(gate):08X} ({len(gate)} bytes)")
    print(f"High RAM blob: {len(highram_blob)} bytes SHA-256 {hashlib.sha256(highram_blob).hexdigest()}")
    print(f"Max authority game payload: {max_payload} bytes (1 human record + 7 CPU)")
    if args.ips:
        print(f"IPS: {args.ips}")
    print(f"Header: {args.cpp_header}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
