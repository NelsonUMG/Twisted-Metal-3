#!/usr/bin/env python3
"""Create an isolated mkpsxiso project for the AI-owner v19 SCUS."""

from __future__ import annotations

import argparse
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path


EXPECTED_SCUS_SHA256 = "db00b41372a1c3b68291b19429f3cd62da784b4d5e6d8abe583ab8e754d21c7a"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara el disco aislado TM3 AI-owner v19")
    parser.add_argument("template", type=Path)
    parser.add_argument("scus", type=Path)
    parser.add_argument("output_xml", type=Path)
    parser.add_argument("--bin", default="TM3_AI_OWNER_V19.bin")
    parser.add_argument("--cue", default="TM3_AI_OWNER_V19.cue")
    args = parser.parse_args()

    digest = hashlib.sha256(args.scus.read_bytes()).hexdigest()
    if digest != EXPECTED_SCUS_SHA256:
        raise SystemExit(f"ERROR: SCUS v19 inesperado: {digest}")

    tree = ET.parse(args.template)
    root = tree.getroot()
    if root.tag != "iso_project":
        raise SystemExit("ERROR: la plantilla no contiene iso_project")
    root.set("image_name", args.bin)
    root.set("cue_sheet", args.cue)

    matches = [
        element for element in root.iter("file")
        if element.get("name", "").upper() == "SCUS_942.49"
    ]
    if len(matches) != 1:
        raise SystemExit(f"ERROR: SCUS_942.49 encontrados={len(matches)}")
    matches[0].set("source", args.scus.as_posix())

    ET.indent(tree, space="    ")
    args.output_xml.parent.mkdir(parents=True, exist_ok=True)
    tree.write(args.output_xml, encoding="utf-8", xml_declaration=False)
    print(f"OK: {args.output_xml}")
    print(f"SCUS SHA-256: {digest}")
    print(f"Salida: {args.bin} / {args.cue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
