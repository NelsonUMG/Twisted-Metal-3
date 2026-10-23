"""Read-only, reproducible Ghidra-style xref audit of the packaged TM3 disc.

Uses existing Ghidra function/PC exports only as address labels. Instructions,
direct edges and evidence bytes come from the executable extracted from the
actual MODE2/2352 disc. This is not a decompiler or a runtime profiler.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "133d4cb7a59c059d99d41d61cca06c1ddf147753f2d951c5c27a6303d737f502"
GP = 0x800894C0
RANGES = {
    "startup_gp": (0x80062398, 0x800623C4),
    "time_reader": (0x8003A0E4, 0x8003A0F0),
    "main_loop": (0x8003A18C, 0x8003AFB4),
    "render_context": (0x8003DB00, 0x8003DDC4),
    "presentation": (0x8003DDC4, 0x8003E084),
    "presentation_gate": (0x8003E084, 0x8003E1F4),
    "timer_callbacks": (0x800435A4, 0x8004367C),
    "world_update": (0x8004AB6C, 0x8004ABCC),
    "collision_pairs": (0x8004A82C, 0x8004A96C),
    "object_callbacks": (0x8004AAA8, 0x8004AB6C),
    "vehicle_post_control": (0x8001F948, 0x8001FBA4),
    "vehicle_callback": (0x80018338, 0x8001862C),
    "constraints": (0x8001FBA4, 0x8001FEE8),
    "physics": (0x8001FEE8, 0x800204F4),
    "normalize": (0x800146A4, 0x800148DC),
    "magnitude": (0x80013D08, 0x80013D64),
    "sqrt_dispatch": (0x80013C00, 0x80013C84),
    "sqrt_fast_cave": (0x80047800, 0x800478F0),
    "sqrt_merge_cave": (0x80047B50, 0x80047C00),
    "dot_product": (0x80013A90, 0x80013B18),
    "geometry": (0x80013484, 0x80013A90),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def disc_file(path, name):
    """ISO9660 root file, bounded reads; never reads audio as filesystem data."""
    with path.open("rb") as stream:
        def block(lba):
            stream.seek(lba * 2352)
            raw = stream.read(2352)
            if len(raw) != 2352 or raw[:12] != b"\x00" + b"\xff" * 10 + b"\x00" or raw[15] != 2:
                raise ValueError("Expected MODE2/2352 data sector")
            if raw[16:20] != raw[20:24] or raw[18] & 0x20:
                raise ValueError("Expected duplicated MODE2 Form1 subheader")
            return raw[24:24 + 2048]

        def extent(lba, size):
            if not 0 < size <= 16 * 1024 * 1024:
                raise ValueError("Unexpected extent size")
            return b"".join(block(lba + i) for i in range((size + 2047) // 2048))[:size]

        pvd = block(16)
        if pvd[:7] != b"\x01CD001\x01":
            raise ValueError("ISO9660 primary descriptor missing")
        directory = extent(struct.unpack_from("<I", pvd, 158)[0],
                           struct.unpack_from("<I", pvd, 166)[0])
        offset = 0
        while offset < len(directory):
            length = directory[offset]
            if not length:
                offset = ((offset // 2048) + 1) * 2048
                continue
            record = directory[offset:offset + length]
            if len(record) < 34:
                raise ValueError("Truncated directory record")
            filename = record[33:33 + record[32]].decode("ascii", errors="replace")
            if filename.split(";")[0].upper() == name.upper():
                lba = struct.unpack_from("<I", record, 2)[0]
                size = struct.unpack_from("<I", record, 10)[0]
                return extent(lba, size), {"name": filename, "lba": lba, "bytes": size}
            offset += length
    raise ValueError("Executable missing from ISO root")


def word(blob, pc):
    return struct.unpack_from("<I", blob, 0x800 + pc - 0x80010000)[0]


def direct_edge(pc, value):
    opcode = value >> 26
    if opcode in (2, 3):
        return {"site": f"{pc:08X}", "target": f"{((pc + 4) & 0xF0000000) | ((value & 0x3FFFFFF) << 2):08X}",
                "kind": "call" if opcode == 3 else "jump"}
    return None


def audit(disc, output):
    blob, location = disc_file(disc, "SCUS_942.49")
    if blob[:8] != b"PS-X EXE" or sha(blob) != EXPECTED:
        raise ValueError("Disc executable is not the audited SqrtMergeV4 candidate")
    source = ROOT / "diagnostics/sqrt_merge_v4/SCUS_942.49.sqrt_merge_v4"
    if source.read_bytes() != blob:
        raise ValueError("Disc and candidate executable differ")
    # Actual startup instructions establish GP; do not trust its zero EXE-header field.
    evidence_words = {
        0x80062398: 0x3C1C8009, 0x8006239C: 0x279C94C0,
        0x8003AA54: 0x8E820004, 0x8003AA5C: 0x1040005C,
        0x8003AC10: 0x0C012ADB, 0x8003ACA4: 0x0C00F771,
        0x8003ACAC: 0x0C00F821, 0x8003AF84: 0x8F8200E8,
        0x8003AF8C: 0x24420001, 0x8003AF90: 0xAF8200E8,
        0x800146BC: 0x0C004F42, 0x800146D0: 0x0050001A,
        0x80020330: 0x0C007EE9,
    }
    for pc, expected in evidence_words.items():
        if word(blob, pc) != expected:
            raise ValueError(f"Evidence instruction changed at {pc:08X}")
    sys.path.insert(0, str(ROOT / ".codex_tmp_capstone"))
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
    decoder = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    pcmap_path = ROOT / "diagnostics/tm3_profile_pcmap_v20.csv"
    pcmap = {int(r["pc"], 16): r["function_name"] for r in csv.DictReader(pcmap_path.open())}
    edges, gp_refs = [], []
    # Only historical known code addresses, not a scan pretending data is code.
    for pc in sorted(pcmap):
        value = word(blob, pc)
        edge = direct_edge(pc, value)
        if edge:
            edge.update(caller=pcmap[pc], target_label=pcmap.get(int(edge["target"], 16), "unmapped_or_patch"))
            edges.append(edge)
        op, base = value >> 26, (value >> 21) & 31
        if base == 28 and op in (32, 33, 35, 36, 37, 40, 41, 43):
            displacement = value & 65535
            displacement -= 65536 if displacement & 32768 else 0
            gp_refs.append({"site": f"{pc:08X}", "address": f"{(GP + displacement) & 0xFFFFFFFF:08X}",
                            "kind": "store" if op in (40, 41, 43) else "load", "function": pcmap[pc]})
    baseline_path = ROOT / "TM3_EXTRAIDO/SCUS_942.49"
    baseline = baseline_path.read_bytes()
    if sha(baseline) != "31b296f58fc3d8892358f5ef27046bd3d993b001d564f0ffa0d2a9adf9cd3ae5":
        raise ValueError("Expected known modified V10 comparison baseline")
    output.mkdir(parents=True, exist_ok=False)
    verified_ranges = {}
    for label, (lo, hi) in RANGES.items():
        segment = blob[0x800 + lo - 0x80010000:0x800 + hi - 0x80010000]
        lines = []
        for pc in range(lo, hi, 4):
            raw = struct.pack("<I", word(blob, pc))
            insns = list(decoder.disasm(raw, pc, count=1))
            text = f"{insns[0].mnemonic} {insns[0].op_str}" if insns else f".word 0x{word(blob, pc):08X}"
            lines.append(f"{pc:08X}  {word(blob, pc):08X}  {text.rstrip()}")
        (output / (label + ".asm")).write_text("\n".join(lines) + "\n", encoding="utf-8")
        verified_ranges[label] = {"start": f"{lo:08X}", "end_exclusive": f"{hi:08X}", "sha256": sha(segment),
                                  "equals_modified_v10_baseline_range": segment == baseline[0x800 + lo - 0x80010000:0x800 + hi - 0x80010000]}
    time_refs = [r for r in gp_refs if r["address"] == "800895A8"]
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "method": "actual-disc disassembly + Ghidra-export labels + GP data xrefs + direct control edges",
              "disc": str(disc.resolve()), "disc_size": disc.stat().st_size, "iso_file": location,
              "executable_sha256": sha(blob), "candidate_matches_disc": True, "gp": f"{GP:08X}",
              "verified_evidence_words": {f"{pc:08X}": f"{v:08X}" for pc, v in evidence_words.items()},
              "main_loop_words_different_from_modified_v10": [f"{pc:08X}" for pc in range(*RANGES["main_loop"], 4) if word(blob, pc) != word(baseline, pc)],
              "vehicle_type0_update_pointer": f"{word(blob, 0x8007F270):08X}",
              "pcmap_sha256": sha(pcmap_path.read_bytes()), "comparison_baseline": {"path": str(baseline_path), "sha256": sha(baseline), "kind": "modified_V10_not_pristine_retail"},
              "ranges": verified_ranges, "time_gp_xrefs": time_refs,
              "gp_data_xrefs": gp_refs, "direct_edges": edges,
              "limitations": ["Static references do not measure runtime cost or prove a unique defect.",
                              "Labels/PC ownership are historical; modified instruction bytes are current.",
                              "The V10 baseline is already modified; equality does not certify equality to an untouched retail disc.",
                              "Indirect calls, computed addresses, overlays and edges outside the historical PC map are incomplete.",
                              "GP references assume the startup ABI established by the verified instructions.",
                              "No claim that Ghidra itself was run: existing exports plus a fresh Capstone disassembly.",
                              "No game process, emulator clock, configuration or disc was modified."]}
    (output / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disc", type=Path, default=ROOT / "TM3Online_Lobby/runtime/game/TM3_SQRT_MERGE_V4.bin")
    parser.add_argument("--output", type=Path, default=ROOT / "diagnostics/offline_bin_audit_v1" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_UTC"))
    args = parser.parse_args()
    report = audit(args.disc, args.output)
    print(json.dumps({k: report[k] for k in ("method", "iso_file", "executable_sha256", "candidate_matches_disc", "time_gp_xrefs", "ranges")}, indent=2))
    print("OUTPUT", args.output.resolve())
