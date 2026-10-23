#!/usr/bin/env python3
"""Create a mkpsxiso project that boots the retail SCUS used by PSXRecomp.

All media/data files continue to reference the preserved TM3_EXTRAIDO tree.
Only SCUS_942.49 gets an explicit source override, so neither the v9/v10 BINs
nor the extracted patched executable are overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path


ORIGINAL_SHA256 = (
    "2bb2a618889a057627a79d2a01cd53b83c6dbc12b9ea49a5f621b6179c5e8998"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepara XML reproducible del disco retail para PSXRecomp"
    )
    parser.add_argument("template", type=Path)
    parser.add_argument("original_scus", type=Path)
    parser.add_argument("output_xml", type=Path)
    parser.add_argument("--bin", default="TM3_LINK_ORIGINAL.bin")
    parser.add_argument("--cue", default="TM3_LINK_ORIGINAL.cue")
    args = parser.parse_args()

    digest = hashlib.sha256(args.original_scus.read_bytes()).hexdigest()
    if digest != ORIGINAL_SHA256:
        raise SystemExit(
            f"ERROR: SCUS retail inesperado: {digest}; esperado {ORIGINAL_SHA256}"
        )

    tree = ET.parse(args.template)
    root = tree.getroot()
    if root.tag != "iso_project":
        raise SystemExit("ERROR: la plantilla no contiene iso_project")
    root.set("image_name", args.bin)
    root.set("cue_sheet", args.cue)

    matches = [
        element
        for element in root.iter("file")
        if element.get("name", "").upper() == "SCUS_942.49"
    ]
    if len(matches) != 1:
        raise SystemExit(f"ERROR: se esperÃ³ un SCUS_942.49, encontrados={len(matches)}")
    matches[0].set("source", args.original_scus.as_posix())

    ET.indent(tree, space="    ")
    args.output_xml.parent.mkdir(parents=True, exist_ok=True)
    tree.write(args.output_xml, encoding="utf-8", xml_declaration=False)
    print(f"OK: {args.output_xml}")
    print(f"SCUS: {args.original_scus} SHA-256={digest}")
    print(f"Salida: {args.bin} / {args.cue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
