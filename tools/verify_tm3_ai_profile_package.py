#!/usr/bin/env python3
"""Verifica el paquete aislado TM3 AI Profile V2 sin ejecutar el juego."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SHA256 = {
    "TM3_EXTRAIDO/SCUS_942.49":
        "31b296f58fc3d8892358f5ef27046bd3d993b001d564f0ffa0d2a9adf9cd3ae5",
    "TM3_EXTRAIDO/SCUS_942.49.rngcaller_diag_v12":
        "56fc9301f987a6e6f22402ae7266652c70ede09ce8c02a666828e48152c74843",
    "frontend/build/Release/cores/beetle_psx_libretro.dll":
        "1e057ffae609e633aa4d371b561f41bd94109fc557efb1758d760cbe9138f0c9",
    "frontend/build/Release/cores/beetle_psx_aiprofile.dll":
        "11ee3d20ae7b86415da7cf3a8d844adb53bf085d9b6efe3168db3843f15b7f34",
    "frontend/build/Release/TM3Online_Oscar_AIProfile.exe":
        "5a6b66a1c7fbf7b428ad4e0b33971507037d29c3dbdd75c773b06db85838b80b",
    "frontend/build/Release/TM3Online_Sofia_AIProfile.exe":
        "5a6b66a1c7fbf7b428ad4e0b33971507037d29c3dbdd75c773b06db85838b80b",
    "frontend/build/Release/cores/beetle_psx_aiprofile_v3.dll":
        "66cbe7e95ea923b908c1c9d752f05c6dcfcf4eedb1a8c5851ecfbba761cd0547",
    "frontend/build/Release/TM3Online_Oscar_AIProfileV3.exe":
        "5f7d35ab6002d18e0a8e8ba5d3354371ba61e9ffdb0e12716dfaf53d5c2ddeb5",
    "frontend/build/Release/TM3Online_Sofia_AIProfileV3.exe":
        "5f7d35ab6002d18e0a8e8ba5d3354371ba61e9ffdb0e12716dfaf53d5c2ddeb5",
    "frontend/build/Release/game_rngcaller/TM3_RNGCALLER_DIAG.bin":
        "4a0463cce1081ea667f3aca94dcf62cd110e88cf35a26b2b9de8c90e481e4d11",
    "frontend/build/Release/game_rngcaller/TM3 RNGCaller.cue":
        "61dc8430d3937f0c1bc7c764206fa5e6527b64bba573230544b5b4c9a3511005",
}

REQUIRED_FUNCTIONS = {
    0x80016EA8,  # path search, llamada desde 0x8001BF38
    0x80018338,
    0x8001A390,
    0x8001A40C,
    0x8001B100,
    0x8001BC78,
    0x8001BF10,
    0x8001F948,
    0x800211D4,
    0x8003A0E4,
    0x8004A82C,
    0x8004AAA8,
    0x8004AB6C,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_hashes() -> None:
    for relative, expected in EXPECTED_SHA256.items():
        path = ROOT / relative
        if not path.is_file():
            raise AssertionError(f"falta: {relative}")
        actual = sha256(path)
        if actual != expected:
            raise AssertionError(f"hash inesperado: {relative}: {actual}")


def verify_memory_layout() -> None:
    event_begin = 0xC00100
    v2_event_end = event_begin + 4096 * 0xA0
    v3_event_end = event_begin + 4096 * 0xF0
    histogram_begin = 0xD00000
    histogram_end = histogram_begin + ((0x80070000 - 0x80010000) // 4) * 4 * 4
    rngcaller_begin = 0xF00000
    rngcaller_end = 0xF10100 + 15 * 4
    assert 0xC00000 < event_begin < v2_event_end <= histogram_begin
    assert event_begin < v3_event_end <= histogram_begin
    assert histogram_begin < histogram_end <= rngcaller_begin
    assert rngcaller_begin < rngcaller_end <= 0x1000000


def verify_static_map() -> tuple[int, int, int, int]:
    functions_path = ROOT / "diagnostics/tm3_profile_functions_v20.csv"
    calls_path = ROOT / "diagnostics/tm3_profile_calls_v20.csv"
    pc_map_path = ROOT / "diagnostics/tm3_profile_pcmap_v20.csv"
    references_path = ROOT / "diagnostics/tm3_profile_target_refs_v20.csv"
    with functions_path.open(newline="", encoding="utf-8-sig") as stream:
        functions = list(csv.DictReader(stream))
    with calls_path.open(newline="", encoding="utf-8-sig") as stream:
        calls = list(csv.DictReader(stream))
    with pc_map_path.open(newline="", encoding="utf-8-sig") as stream:
        pc_map = list(csv.DictReader(stream))
    with references_path.open(newline="", encoding="utf-8-sig") as stream:
        references = list(csv.DictReader(stream))
    entries = {int(row["entry"], 0) for row in functions}
    missing = REQUIRED_FUNCTIONS - entries
    if missing:
        formatted = ", ".join(f"0x{value:08X}" for value in sorted(missing))
        raise AssertionError(f"faltan funciones objetivo en el mapa: {formatted}")
    if not any(int(row["call_site"], 0) == 0x8001BF38 and
               int(row["destination"], 0) == 0x80016EA8 for row in calls):
        raise AssertionError("falta el JAL 0x8001BF38 -> 0x80016EA8")
    labels = {int(row["pc"], 0): row["function_name"] for row in pc_map}
    if labels.get(0x8001A40C) != "FUN_8001a40c":
        raise AssertionError("atribución exacta de PC 0x8001A40C incorrecta")
    path_wrapper_callers = {
        int(row["from_address"], 0)
        for row in references
        if int(row["target"], 0) == 0x8001BF10
    }
    if path_wrapper_callers != {0x8001B0BC, 0x8001C29C}:
        raise AssertionError("callers verificados de 0x8001BF10 cambiaron")
    return len(functions), len(calls), len(pc_map), len(references)


def verify_sources() -> None:
    analyzer = (ROOT / "tools/analyze_tm3_ai_profile.py").read_text(encoding="utf-8")
    compile(analyzer, "tools/analyze_tm3_ai_profile.py", "exec")
    core = (ROOT / "third_party/beetle-psx-libretro-c27ab27c05569575e04b25e03e87fe3220fde599/mednafen/psx/cpu.c").read_text(encoding="utf-8")
    frontend = (ROOT / "diagnostics/rngcaller_frontend_v12/src/net_bridge.cpp").read_text(encoding="utf-8")
    for marker in ("TM3O_AI_PROFILE", "0x00C00000U", "0xF0U", "0x8001A40CU",
                   "0x8001BF10U", "0x80016EA8U", "vehicle_offset + 0x0D3AU",
                   "0x8003AA98U"):
        if marker not in core:
            raise AssertionError(f"falta marker del core: {marker}")
    for marker in ("dropped_events=", "RANDOM_MISMATCH", "TIME_MISMATCH"):
        if marker not in frontend:
            raise AssertionError(f"falta marker del frontend: {marker}")


def main() -> int:
    verify_hashes()
    verify_memory_layout()
    function_count, call_count, pc_count, reference_count = verify_static_map()
    verify_sources()
    print("OK: paquetes TM3 AI Profile V2/V3 aislados y hashes estables conservados")
    print(f"OK: mapa estático: {function_count} funciones, {call_count} llamadas directas, "
          f"{pc_count} PCs exactos, {reference_count} referencias objetivo")
    print("OK: RAM AI profile 0xC00000..0xE7FFFF; RNGCaller v12 desde 0xF00000")
    print("NOTA: esta verificación no ejecuta el juego ni afirma FPS/determinismo dinámico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
