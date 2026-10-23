"""Inspect Qt layout structure in the pinned local reference; never copies UI source into our executable."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


def audit(reference):
    root = reference / "src/duckstation-qt"
    commit = subprocess.check_output(["git", "-C", str(reference), "rev-parse", "HEAD"], text=True).strip()
    documents = []
    for path in sorted(root.glob("*.ui")):
        tree = ET.parse(path).getroot()
        widgets = tree.findall(".//widget")
        documents.append(dict(file=path.name, widget_count=len(widgets),
                              groups=[w.attrib["name"] for w in widgets if w.attrib.get("class") == "QGroupBox"],
                              tabs=[w.attrib["name"] for w in widgets if w.attrib.get("class") == "QTabWidget"],
                              stacks=[w.attrib["name"] for w in widgets if w.attrib.get("class") == "QStackedWidget"],
                              classes=sorted({w.attrib.get("class", "") for w in widgets})))
    code = []
    for path in sorted(root.glob("*.cpp")):
        text = path.read_text(encoding="utf-8-sig")
        code.append(dict(file=path.name, lines=len(text.splitlines()),
                         signal_connections=len(re.findall(r"\bconnect\s*\(", text)),
                         setting_bindings=len(re.findall(r"SettingWidgetBinder::Bind", text))))
    return dict(commit=commit, ui_files=len(documents), cpp_files_indexed=len(code),
                license="CC-BY-NC-ND-4.0", source_copied_into_our_console=False,
                ui=documents, cpp_index=code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.reference.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "structure.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("ui", "cpp_index")}, indent=2))
