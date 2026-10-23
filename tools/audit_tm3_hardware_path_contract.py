"""Read-only verification of the TM3 research findings dated 2026-09-26.

No game process, ROM, emulator state or output file is modified. This is a
static BIN/SCUS audit, NOT a hardware emulator or a successful gameplay test.
Run: py -3.14 tools/audit_tm3_hardware_path_contract.py --self-test
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "original_menu_only": (
        "TM3_EXTRAIDO/SCUS_942.49.menu_only_backup",
        "24fc2707d63ceaab857105c6b9bbf1e344054ace116c97d538c478310ba4d765",
    ),
    "v10": (
        "TM3_EXTRAIDO/SCUS_942.49.modern_batch_16mib_v10",
        "31b296f58fc3d8892358f5ef27046bd3d993b001d564f0ffa0d2a9adf9cd3ae5",
    ),
    "v12": (
        "TM3_EXTRAIDO/SCUS_942.49.rngcaller_diag_v12",
        "56fc9301f987a6e6f22402ae7266652c70ede09ce8c02a666828e48152c74843",
    ),
}
REGIONS = (
    ("graph_flag_writer", 0x80016D28, 0x80016EA8,
     "24a8872dd858cc90ae82333f04bd9eaa59904cc6361089786bad361f3c5767d9"),
    ("path_search", 0x80016EA8, 0x8001746C,
     "e81cc8978818368ad2bb049df6f3f53dfd21f1dff4eff56f227969cd9eaf68f6"),
    ("graph_initialization_caller", 0x800157E8, 0x80015904,
     "0dd05d52a2108a10f5af362f7bb58fb19e10122fece8086cece482edb9693c1b"),
    ("object_state_caller", 0x80012C20, 0x80012E48,
     "537040bc3267c7c8665c64af94f0d552ab180ad274e9ff2bc50c846560fe9fa6"),
    ("graphics_reset_dispatch", 0x800574CC, 0x80057640,
     "a6b7f9bfeeb39dec44f5209275fe40abb68ce27bcaf2b2bc6fe8a40490ef2993"),
    ("graphics_reset_worker", 0x80059BCC, 0x80059D1C,
     "591df941d25539b49d087a2b95dafdfbdcc5df1ec8b8e7a3169165e625a63799"),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def region(blob, start, end):
    require(blob[:8] == b"PS-X EXE", "not a PS-X EXE")
    base = struct.unpack_from("<I", blob, 0x18)[0]
    offset = 0x800 + start - base
    require(end >= start and offset >= 0x800, "invalid mapped range")
    require(offset + end - start <= len(blob), "range outside executable")
    return blob[offset:offset + end - start]


def word(blob, address):
    return struct.unpack("<I", region(blob, address, address + 4))[0]


def branch_target(pc, instruction):
    imm = instruction & 0xFFFF
    if imm & 0x8000:
        imm -= 0x10000
    return (pc + 4 + 4 * imm) & 0xFFFFFFFF


def verify_contract(original, v12):
    checked = []
    for name, lo, hi, expected in REGIONS:
        raw = region(original, lo, hi)
        require(hashlib.sha256(raw).hexdigest() == expected, name + " changed in original")
        require(raw == region(v12, lo, hi), name + " differs in v12")
        checked.append({"name": name, "start": hex(lo), "end_exclusive": hex(hi),
                        "sha256": expected, "identical_original_v12": True})

    for address, expected in {
        0x80012DA8: 0x0C005B4A,  # jal graph flag writer
        0x800158AC: 0x0C005B4A,
        0x80016E9C: 0xA044000B,  # sb a0, 0xb(v0), in branch delay slot
        0x80016F14: 0x9782001E,  # lhu v0, 0x1e(gp)
        0x80016F18: 0x241E1387,  # literal 4999, NOT a timer read
        0x80016F2C: 0xA782001E,
        0x80017158: 0x0C00E83C,  # jal RNG
        0x80017430: 0x1C40FED4,  # bgtz old iteration budget
        0x80017434: 0x27DEFFFF,  # decrement in delay slot
        0x80047FF8: 0x0C018C53,  # jal comb_control
        0x80063600: 0x0C015D33,  # jal graphics reset dispatcher
        0x80059C7C: 0xAC400000,  # write 0 to the indirect GP1 address
        0x80080F58: 0x1F801814,  # GP1 pointer initial value
        0x80080F64: 0x1F8010A8,  # DMA2 CHCR pointer initial value
        0x80080F74: 0x1F8010F0,  # DPCR pointer initial value
    }.items():
        require(word(original, address) == expected, f"original word changed at {address:08X}")
        require(word(v12, address) == expected, f"v12 word changed at {address:08X}")

    old_branch = word(original, 0x80047F18)
    new_branch = word(v12, 0x80047F18)
    require(old_branch == 0x16A00051, "original conditional negotiation branch changed")
    require(new_branch == 0x10000051, "v12 unconditional negotiation bypass changed")
    require(branch_target(0x80047F18, new_branch) == 0x80048060, "wrong bypass target")

    calls = []
    for pc in range(0x80016EA8, 0x8001746C, 4):
        ins = word(original, pc)
        if ins >> 26 == 3:
            calls.append({"pc": hex(pc), "target": hex(((pc + 4) & 0xF0000000) |
                                                        ((ins & 0x03FFFFFF) << 2))})
        require(not (ins >> 26 == 0 and ins & 0x3F == 9), "unexpected jalr in path search")
    require(calls == [{"pc": "0x80017158", "target": "0x8003a0f0"}], "path call graph changed")
    return {"verified_regions": checked, "path_direct_calls": calls,
            "v12_negotiation_bypass": {"pc": "0x80047f18", "target": "0x80048060",
                                      "original": "bnez s5", "v12": "unconditional"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    blobs = {}
    hashes = {}
    for name, (filename, expected) in EXPECTED.items():
        blobs[name] = (ROOT / filename).read_bytes()
        actual = hashlib.sha256(blobs[name]).hexdigest()
        require(actual == expected, f"unexpected {name} SHA-256: {actual}")
        hashes[name] = actual
    original = blobs["original_menu_only"]
    restored = bytearray(original)
    restored[0x78DBC:0x78DBC + 12] = b"LINKED GAME?"
    require(hashlib.sha256(restored).hexdigest() ==
            "2bb2a618889a057627a79d2a01cd53b83c6dbc12b9ea49a5f621b6179c5e8998",
            "menu-only backup cannot reconstruct original hash")
    result = verify_contract(original, blobs["v12"])
    result.update({"status": "PASS_STATIC_ONLY", "hashes": hashes,
                   "hardware_timing_validated": False, "game_determinism_validated": False})
    if args.self_test:
        rejected = []
        for pc in (0x80016E9C, 0x80017158, 0x80047F18):
            mutated = bytearray(blobs["v12"])
            base = struct.unpack_from("<I", mutated, 0x18)[0]
            mutated[0x800 + pc - base] ^= 1
            try:
                verify_contract(original, mutated)
            except ValueError:
                rejected.append(hex(pc))
            else:
                raise ValueError(f"self-test failed to reject mutation at {pc:08X}")
        result["self_test_mutations_rejected"] = rejected
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
