#!/usr/bin/env python3
"""Deterministic protocol simulation for AI-owner v19.

This is deliberately not an emulator or a claim of in-game stability.  It
checks the causal contract implemented by the MIPS patch across every intended
human/CPU count: boundary comparison first, transactional control application,
post-AI RNG adoption, and one-fragment payload sizing.
"""

from __future__ import annotations

import copy
import struct
from dataclasses import dataclass, field


MAGIC = 0x39314941
HEADER_SIZE = 16
RECORD_SIZE = 52
UDP_FRAGMENT = 1200


def lcg(seed: int) -> int:
    return (seed * 0x41C64E6D + 0x3039) & 0xFFFFFFFF


@dataclass
class Vehicle:
    roster: int
    controls: list[int] = field(default_factory=lambda: [0] * 11)
    event: int = 0
    position: int = 0


@dataclass
class Console:
    seed: int
    vehicles: list[Vehicle]


def evaluate_authority(console: Console, human_count: int, tick: int) -> tuple[int, int, bytes]:
    pre_seed = console.seed
    cpus = console.vehicles[human_count:]
    if tick & 1 == 0:
        for vehicle in cpus:
            calls = 1 + ((vehicle.roster ^ tick ^ vehicle.position) & 3)
            for _ in range(calls):
                console.seed = lcg(console.seed)
            vehicle.controls = [
                (console.seed ^ (vehicle.roster * 0x10101) ^ (tick * (index + 1))) & 0xFFFFFFFF
                for index in range(11)
            ]
            vehicle.event = (console.seed >> 29) & 7

    scratch = bytearray(struct.pack("<IIII", pre_seed, console.seed, len(cpus), MAGIC))
    for vehicle in cpus:
        scratch.extend(struct.pack("<I11II", vehicle.roster, *vehicle.controls, vehicle.event))
    assert len(scratch) == HEADER_SIZE + len(cpus) * RECORD_SIZE
    return pre_seed, console.seed, bytes(scratch)


def apply_follower(console: Console, human_count: int, scratch: bytes) -> tuple[bool, int, int]:
    if len(scratch) < HEADER_SIZE:
        return False, 0, 0
    pre_seed, post_seed, cpu_count, magic = struct.unpack_from("<IIII", scratch)
    if magic != MAGIC or cpu_count > 7 or len(scratch) != HEADER_SIZE + cpu_count * RECORD_SIZE:
        return False, 0, 0
    cpus = console.vehicles[human_count:]
    if len(cpus) != cpu_count:
        return False, 0, 0

    records = []
    for index in range(cpu_count):
        record = struct.unpack_from("<I11II", scratch, HEADER_SIZE + index * RECORD_SIZE)
        if cpus[index].roster != record[0]:
            return False, 0, 0
        records.append(record)

    for vehicle, record in zip(cpus, records):
        vehicle.controls = list(record[1:12])
        vehicle.event = record[12]
    console.seed = post_seed
    return True, pre_seed, post_seed


def advance_world(console: Console, human_count: int) -> None:
    for vehicle in console.vehicles[human_count:]:
        vehicle.position = (vehicle.position + (vehicle.controls[0] & 0xFF) - 0x80) & 0xFFFFFFFF
        vehicle.event = 0
    console.seed = lcg(console.seed)


def run_configuration(humans: int, cpus: int, frames: int = 2000) -> None:
    vehicles = [Vehicle(roster=index) for index in range(humans + cpus)]
    authority = Console(seed=0x12345678, vehicles=copy.deepcopy(vehicles))
    follower = Console(seed=0x12345678, vehicles=copy.deepcopy(vehicles))
    for tick in range(frames):
        local_pre = follower.seed
        authority_pre, authority_post, scratch = evaluate_authority(authority, humans, tick)
        assert local_pre == authority_pre
        before = copy.deepcopy(follower.vehicles)
        ok, peer_pre, peer_post = apply_follower(follower, humans, scratch)
        assert ok and peer_pre == local_pre and peer_post == authority_post
        assert follower.vehicles[:humans] == before[:humans]
        assert follower.vehicles[humans:] == authority.vehicles[humans:]

        authority_payload = 4 + 24 + 4 + len(scratch)
        follower_payload = 4 + 24 + 4 + HEADER_SIZE
        assert authority_payload <= UDP_FRAGMENT and follower_payload == 48

        advance_world(authority, humans)
        advance_world(follower, humans)
        assert follower.seed == authority.seed
        assert follower.vehicles == authority.vehicles


def check_fail_closed() -> None:
    vehicles = [Vehicle(roster=index) for index in range(8)]
    authority = Console(seed=0xCAFEBABE, vehicles=copy.deepcopy(vehicles))
    follower = Console(seed=0xCAFEBABE, vehicles=copy.deepcopy(vehicles))
    _, _, scratch = evaluate_authority(authority, 2, 0)

    corrupted = bytearray(scratch)
    struct.pack_into("<I", corrupted, HEADER_SIZE + RECORD_SIZE, 0xFFFFFFFF)
    before = copy.deepcopy(follower)
    ok, _, _ = apply_follower(follower, 2, bytes(corrupted))
    assert not ok and follower == before

    follower.seed ^= 1
    local_pre = follower.seed
    authority_pre, _, scratch = evaluate_authority(authority, 2, 2)
    ok, peer_pre, _ = apply_follower(follower, 2, scratch)
    assert ok and local_pre != authority_pre and peer_pre == authority_pre
    # The follower adopts post-AI state, but the two captured pre-AI boundary
    # values remain unequal for the original RANDOM SYNC comparison.


def main() -> int:
    for cpus in range(1, 8):
        run_configuration(1, cpus)
    for cpus in range(1, 7):
        run_configuration(2, cpus)
    check_fail_closed()
    print("OK v19 protocol simulation: 13 configurations x 2000 frames")
    print("OK transactional roster rejection and pre-AI mismatch visibility")
    print("OK payload range 48..412 bytes, one UDP fragment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
