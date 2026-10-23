#!/usr/bin/env python3
"""Alinea los rings RNGCaller de Oscar y Sofia por la semilla LCG.

Uso:
  python tools/analyze_rngcaller_dumps.py \
    frontend/build/Release/TM3Online_Oscar.rngcaller.calls.csv \
    frontend/build/Release/TM3Online_Sofia.rngcaller.calls.csv \
    --output evidence/rngcaller_analysis.md
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Call:
    logical: int
    ring_index: int
    ra: int
    caller: int
    seed_before: int
    seed_after: int


def parse_number(value: str) -> int:
    return int(value.strip(), 0)


def load_calls(path: Path) -> list[Call]:
    with path.open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    calls = [
        Call(
            logical=parse_number(row["logical_call"]),
            ring_index=parse_number(row["ring_index"]),
            ra=parse_number(row["ra"]),
            caller=parse_number(row["caller_jal"]),
            seed_before=parse_number(row["seed_before"]),
            seed_after=parse_number(row["seed_after"]),
        )
        for row in rows
    ]
    if any(right.logical <= left.logical for left, right in zip(calls, calls[1:])):
        raise ValueError(f"{path}: logical_call no es estrictamente creciente")
    for call in calls:
        expected = (call.seed_before * 0x41C64E6D + 12345) & 0xFFFFFFFF
        if call.seed_after != expected:
            raise ValueError(
                f"{path}: LCG invalido en logical_call={call.logical}: "
                f"0x{call.seed_after:08X} != 0x{expected:08X}"
            )
    return calls


def fmt_call(call: Call | None) -> str:
    if call is None:
        return "(ninguna)"
    return (
        f"logical={call.logical}, ring={call.ring_index}, "
        f"ra=0x{call.ra:08X}, caller_jal=0x{call.caller:08X}, "
        f"seed=0x{call.seed_before:08X}->0x{call.seed_after:08X}"
    )


def caller_table(calls: list[Call], limit: int = 12) -> list[str]:
    counts = Counter(call.caller for call in calls)
    return [
        f"- `0x{caller:08X}`: {count} llamadas"
        for caller, count in counts.most_common(limit)
    ] or ["- (ninguna llamada adicional)"]


def build_report(oscar: list[Call], sofia: list[Call],
                 oscar_path: Path, sofia_path: Path) -> str:
    oscar_by_seed = {call.seed_before: (index, call) for index, call in enumerate(oscar)}
    common: list[tuple[int, int, Call, Call]] = []
    for sofia_index, sofia_call in enumerate(sofia):
        match = oscar_by_seed.get(sofia_call.seed_before)
        if match is not None:
            oscar_index, oscar_call = match
            common.append((oscar_index, sofia_index, oscar_call, sofia_call))

    lines = [
        "# Análisis RNGCaller",
        "",
        f"- Óscar: `{oscar_path}` ({len(oscar)} entradas)",
        f"- Sofía: `{sofia_path}` ({len(sofia)} entradas)",
        f"- Semillas `seed_before` compartidas: {len(common)}",
        "",
    ]
    if not common:
        lines += [
            "No existe una semilla común dentro de las dos ventanas de 4096 llamadas.",
            "Hace falta aumentar el ring o volcar antes.",
            "",
        ]
        return "\n".join(lines)

    # En una LCG de periodo completo cada seed identifica una posición. El par
    # con mayor avance conjunto es el último estado común dentro de ambos rings.
    oscar_index, sofia_index, common_oscar, common_sofia = max(
        common, key=lambda item: item[0] + item[1]
    )
    oscar_extra = oscar[oscar_index + 1 :]
    sofia_extra = sofia[sofia_index + 1 :]

    lines += [
        "## Último estado común",
        "",
        f"- Óscar: {fmt_call(common_oscar)}",
        f"- Sofía: {fmt_call(common_sofia)}",
        "",
        "## Primera llamada posterior",
        "",
        f"- Óscar: {fmt_call(oscar_extra[0] if oscar_extra else None)}",
        f"- Sofía: {fmt_call(sofia_extra[0] if sofia_extra else None)}",
        "",
        f"- Sufijo adicional de Óscar: {len(oscar_extra)} llamadas",
        f"- Sufijo adicional de Sofía: {len(sofia_extra)} llamadas",
        "",
        "## Callers en el sufijo de Óscar",
        "",
        *caller_table(oscar_extra),
        "",
        "## Callers en el sufijo de Sofía",
        "",
        *caller_table(sofia_extra),
        "",
    ]

    differing_common_callers = [
        (a, b) for _, _, a, b in common if a.caller != b.caller
    ]
    lines += [
        "## Misma semilla consumida por caller diferente",
        "",
        f"Total dentro del solapamiento: {len(differing_common_callers)}",
        "",
    ]
    for oscar_call, sofia_call in differing_common_callers[-20:]:
        lines.append(
            f"- seed `0x{oscar_call.seed_before:08X}`: "
            f"Óscar `0x{oscar_call.caller:08X}`, "
            f"Sofía `0x{sofia_call.caller:08X}`"
        )
    if not differing_common_callers:
        lines.append("- (ninguno)")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("oscar", type=Path)
    parser.add_argument("sofia", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_report(
        load_calls(args.oscar), load_calls(args.sofia), args.oscar, args.sofia
    )
    print(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
