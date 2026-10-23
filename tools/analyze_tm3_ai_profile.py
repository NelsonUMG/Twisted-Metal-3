#!/usr/bin/env python3
"""Analyze TM3O AI-profile V2 events and PC histograms.

The collector lives in Beetle's precise interpreter.  All reported costs are
emulated instruction/timestamp deltas; host wall-time is intentionally not
treated as a gameplay FPS measurement.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


PC_BEGIN = 0x80010000
PC_END = 0x80070000
HIST_CATEGORIES = (
    "vehicle_update",
    "cpu_callback",
    "path_search",
    "post_control",
)
STATE_FIELDS = tuple(f"f{offset:x}" for offset in range(0x58, 0x84, 4)) + ("f9c",)
PATH_NUMERIC_FIELDS = {"d3a", "path_generation", "d3e", "d42", "d43", "e84", "e86"}
PATH_HEX_FIELDS = {
    "a0", "a1", "a2", "a3", "v0", "v1", "d44", "d48", "graph_base",
    *(f"node{index}" for index in range(7)),
}


def number(value: str) -> int:
    return int(value, 0)


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def fmt_int(value: float | int) -> str:
    return f"{value:,.1f}" if isinstance(value, float) else f"{value:,}"


@dataclass
class ParsedEvents:
    rows: list[dict[str, int | str]]
    malformed_rows: int = 0


def read_events(path: Path) -> ParsedEvents:
    rows: list[dict[str, int | str]] = []
    malformed_rows = 0
    numeric = {
        "event_seq", "target_id", "timestamp", "instruction",
        "duration_instructions", "duration_timestamp", "boundary_ordinal",
        "vehicle_order", "table_index", "f50", "driver_type", "d06", "d08",
        "gp_e8", "registered", "cpu_count", "human_count", "net_humans",
    }
    numeric.update(PATH_NUMERIC_FIELDS)
    hex_numeric = {"pc", "ra", "sp", "gp", "vehicle", "callback", "seed", "scope_flags"}
    hex_numeric.update(STATE_FIELDS)
    hex_numeric.update(PATH_HEX_FIELDS)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for raw in csv.DictReader(stream):
            row: dict[str, int | str] = dict(raw)
            required = (numeric | hex_numeric) & raw.keys()
            if any(raw.get(key) in (None, "") for key in required):
                malformed_rows += 1
                continue
            for key in required:
                row[key] = number(raw[key])
            rows.append(row)
    return ParsedEvents(rows, malformed_rows)


def read_pc_labels(path: Path) -> list[str]:
    labels = ["unattributed"] * ((PC_END - PC_BEGIN) // 4)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            pc = number(row["pc"])
            if PC_BEGIN <= pc < PC_END and (pc - PC_BEGIN) % 4 == 0:
                labels[(pc - PC_BEGIN) // 4] = row["function_name"]
    return labels


def read_histogram(path: Path) -> list[tuple[int, ...]]:
    words_per_category = (PC_END - PC_BEGIN) // 4
    expected = words_per_category * len(HIST_CATEGORIES) * 4
    data = path.read_bytes()
    if len(data) != expected:
        raise ValueError(f"histograma de {len(data)} bytes; esperado {expected}")
    words = struct.unpack(f"<{words_per_category * len(HIST_CATEGORIES)}I", data)
    return [
        words[index * words_per_category:(index + 1) * words_per_category]
        for index in range(len(HIST_CATEGORIES))
    ]


def read_meta(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            result[key.strip()] = value.strip()
    return result


def capture_integrity(events: list[dict[str, int | str]], meta: dict[str, str],
                      malformed_rows: int = 0) -> list[str]:
    sequences = [int(row["event_seq"]) for row in events]
    missing = max(sequences[0] - 1, 0) if sequences else 0
    reversed_or_duplicate = 0
    for previous, current in zip(sequences, sequences[1:]):
        if current > previous:
            missing += current - previous - 1
        else:
            reversed_or_duplicate += 1
    expected_total = int(meta.get("events", "0"), 0) if meta else 0
    if sequences and expected_total > sequences[-1]:
        missing += expected_total - sequences[-1]
    collector_dropped = int(meta.get("dropped_events", "0"), 0) if meta else None
    lines = [
        f"- Huecos detectados en `event_seq`: **{missing:,}**; "
        f"secuencias repetidas/fuera de orden: **{reversed_or_duplicate:,}**.",
        f"- Filas CSV incompletas/ilegibles descartadas: **{malformed_rows:,}**.",
    ]
    if collector_dropped is None:
        lines.append("- No se proporcionó `.meta.txt`; no se pudo contrastar el contador del collector.")
    else:
        lines.append(f"- Eventos descartados declarados por el collector: **{collector_dropped:,}**.")
    if missing or reversed_or_duplicate or malformed_rows or (collector_dropped or 0):
        lines.append("- **Captura incompleta:** no usarla para aprobar un corte de optimización.")
    else:
        lines.append("- **Captura íntegra según CSV y collector.**")
    return lines


def summary_table(events: list[dict[str, int | str]]) -> list[str]:
    exits: dict[str, list[dict[str, int | str]]] = defaultdict(list)
    for row in events:
        if row["phase"] == "exit":
            exits[str(row["target"])].append(row)
    output = [
        "| Scope (inclusive) | Calls | Total instructions | Mean | P95 | Max | Mean timestamp Δ |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    ranked = sorted(
        exits.items(),
        key=lambda item: sum(int(row["duration_instructions"]) for row in item[1]),
        reverse=True,
    )
    for target, rows in ranked:
        instructions = [int(row["duration_instructions"]) for row in rows]
        timestamps = [int(row["duration_timestamp"]) for row in rows]
        output.append(
            f"| `{target}` | {len(rows):,} | {sum(instructions):,} | "
            f"{statistics.fmean(instructions):,.1f} | {percentile(instructions, .95):,} | "
            f"{max(instructions):,} | {statistics.fmean(timestamps):,.1f} |"
        )
    return output


def validate_state(events: list[dict[str, int | str]]) -> tuple[list[str], Counter[str]]:
    issues: Counter[str] = Counter()
    vehicle_rows = [row for row in events if int(row["vehicle"]) != 0]
    for row in vehicle_rows:
        registered = int(row["registered"])
        cpu = int(row["cpu_count"])
        humans = int(row["human_count"])
        table_index = int(row["table_index"])
        if registered != cpu + humans:
            issues["registered != cpu_count + human_count"] += 1
        if table_index == 0xFFFFFFFF or table_index >= max(registered, 1):
            issues["vehicle missing from 0x800D3240 table"] += 1
        by_f50 = int(row["f50"]) < int(row["net_humans"])
        by_driver = int(row["driver_type"]) == 1
        if by_f50 != by_driver:
            issues["f50/net-human classification disagrees with vehicle+d00"] += 1

    lines = [
        f"- Eventos con vehículo válido: **{len(vehicle_rows):,}**.",
        f"- Violaciones de `registered == cpu_count + human_count`: "
        f"**{issues['registered != cpu_count + human_count']:,}**.",
        f"- Vehículos no encontrados en `0x800D3240`: "
        f"**{issues['vehicle missing from 0x800D3240 table']:,}**.",
        f"- Desacuerdos `f50 < net_humans` frente a `vehicle+d00 == 1`: "
        f"**{issues['f50/net-human classification disagrees with vehicle+d00']:,}**.",
    ]
    return lines, issues


def order_analysis(events: list[dict[str, int | str]]) -> list[str]:
    updates: dict[int, list[dict[str, int | str]]] = defaultdict(list)
    for row in events:
        if row["target"] == "vehicle_update" and row["phase"] == "enter":
            updates[int(row["boundary_ordinal"])].append(row)
    counts = [len(rows) for ordinal, rows in updates.items() if ordinal != 0]
    if not counts:
        return ["- No hay entradas de `vehicle_update` posteriores a una frontera BATCH."]
    signatures = Counter(
        tuple((int(row["table_index"]), int(row["f50"]), int(row["driver_type"])) for row in rows)
        for ordinal, rows in updates.items() if ordinal != 0
    )
    most_common, frequency = signatures.most_common(1)[0]
    signature_text = " → ".join(
        f"table[{table_index}]/f50={f50}/d00={driver}" for table_index, f50, driver in most_common
    )
    return [
        f"- Fronteras con updates observados: **{len(counts):,}**; vehículos por frontera "
        f"mín/mediana/máx = **{min(counts)}/{statistics.median(counts):g}/{max(counts)}**.",
        f"- Orden más frecuente ({frequency:,}/{len(counts):,} fronteras): `{signature_text}`.",
    ]


def state_delta_analysis(events: list[dict[str, int | str]]) -> list[str]:
    stacks: dict[tuple[str, int], list[dict[str, int | str]]] = defaultdict(list)
    changed: dict[str, Counter[str]] = defaultdict(Counter)
    paired: Counter[str] = Counter()
    seed_changes: Counter[str] = Counter()
    for row in events:
        target = str(row["target"])
        key = (target, int(row["vehicle"]))
        if row["phase"] == "enter":
            stacks[key].append(row)
        elif stacks[key]:
            before = stacks[key].pop()
            paired[target] += 1
            if int(before["seed"]) != int(row["seed"]):
                seed_changes[target] += 1
            for field in STATE_FIELDS:
                if int(before[field]) != int(row[field]):
                    changed[target][field] += 1
    lines = [
        "| Scope | Paired calls | Seed changed | Frequently changed state words |",
        "|---|---:|---:|---|",
    ]
    for target, count in paired.most_common():
        fields = ", ".join(f"`{name}` {hits:,}" for name, hits in changed[target].most_common()) or "none"
        lines.append(f"| `{target}` | {count:,} | {seed_changes[target]:,} | {fields} |")
    return lines


def histogram_analysis(histogram: list[tuple[int, ...]], labels: list[str]) -> list[str]:
    lines: list[str] = []
    for category, words in zip(HIST_CATEGORIES, histogram):
        aggregate: Counter[str] = Counter()
        exact_unknown: Counter[int] = Counter()
        for index, hits in enumerate(words):
            if not hits:
                continue
            label = labels[index]
            aggregate[label] += hits
            if label == "unattributed":
                exact_unknown[PC_BEGIN + index * 4] += hits
        total = sum(aggregate.values())
        lines.extend([
            f"### `{category}`",
            "",
            f"Total contado: **{total:,} instrucciones**.",
            "",
            "| Function | Instructions | Share |",
            "|---|---:|---:|",
        ])
        for name, hits in aggregate.most_common(20):
            share = hits * 100.0 / total if total else 0.0
            lines.append(f"| `{name}` | {hits:,} | {share:.2f}% |")
        if exact_unknown:
            unknown = ", ".join(
                f"`0x{pc:08X}`={hits:,}" for pc, hits in exact_unknown.most_common(8)
            )
            lines.extend(["", f"PCs no atribuidos más activos: {unknown}."])
        lines.append("")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--histogram", type=Path, required=True)
    parser.add_argument("--pc-map", type=Path,
                        default=Path("diagnostics/tm3_profile_pcmap_v20.csv"))
    parser.add_argument("--meta", type=Path,
                        help="meta del collector; por defecto se infiere del .hist.bin")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    parsed_events = read_events(args.events)
    events = parsed_events.rows
    histogram = read_histogram(args.histogram)
    labels = read_pc_labels(args.pc_map)
    inferred_meta = args.histogram.with_name(
        args.histogram.name.removesuffix(".hist.bin") + ".meta.txt"
    )
    meta = read_meta(args.meta if args.meta is not None else inferred_meta)
    validation_lines, issues = validate_state(events)

    boundaries = sum(1 for row in events if row["target"] == "boundary")
    report = [
        "# TM3 AI profile V2",
        "",
        f"Eventos: **{len(events):,}**. Fronteras BATCH: **{boundaries:,}**.",
        "Los costos siguientes son instrucciones/timestamps emulados; no son una afirmación de FPS real.",
        "",
        "## Integridad de captura",
        "",
        *capture_integrity(events, meta, parsed_events.malformed_rows),
        "",
        "## Coste dinámico por scope",
        "",
        *summary_table(events),
        "",
        "## Consistencia de roster y clasificación",
        "",
        *validation_lines,
        "",
        "## Orden real por frontera",
        "",
        *order_analysis(events),
        "",
        "## Pre/post de vehicle+0xF58..0xF80, +0xF9C y seed",
        "",
        *state_delta_analysis(events),
        "",
        "## Hotspots por histograma de PC",
        "",
        *histogram_analysis(histogram, labels),
        "## Resultado falsable",
        "",
        "Un corte de optimización sólo es candidato si domina el histograma, conserva el orden de "
        "eventos y no introduce desacuerdos de roster/clasificación. RANDOM/TIME deben seguir "
        "evaluándose en las trazas de NetBridge; este informe no los oculta.",
        "",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(report), encoding="utf-8")
    print(f"OK: {args.output} ({len(events)} events, {sum(issues.values())} validation issues, "
          f"{parsed_events.malformed_rows} malformed rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
