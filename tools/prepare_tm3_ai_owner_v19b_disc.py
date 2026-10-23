#!/usr/bin/env python3
"""Create an isolated mkpsxiso project for the high-RAM AI-owner v19b SCUS."""

from __future__ import annotations

import argparse
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path


EXPECTED_SCUS_SHA256 = "6f054ceb4de6391032a394ee7790dbaf4d422ddfb75dbd6a2e0b080403dee843"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara el disco aislado TM3 AI-owner v19b high-RAM")
    parser.add_argument("template", type=Path)
    parser.add_argument("scus", type=Path)
    parser.add_argument("output_xml", type=Path)
    parser.add_argument("--bin", default="TM3_AI_OWNER_V19B.bin")
    parser.add_argument("--cue", default="TM3_AI_OWNER_V19B.cue")
    args = parser.parse_args()

    digest = hashlib.sha256(args.scus.read_bytes()).hexdigest()
    if digest != EXPECTED_SCUS_SHA256:
        raise SystemExit(f"ERROR: SCUS v19b inesperado: {digest}")

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
