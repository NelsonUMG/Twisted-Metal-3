"""Build a clean portable package; archive superseded package files recoverably."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "diagnostics/semiproduction175"
PACKAGE = ROOT / "TM3Online_Lobby"
DIST = ROOT / "dist/TM3Online_SemiProduccion_175_20261021"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def source_zip(source, target):
    omitted = {".git", "__pycache__", "build", "Release", "Debug"}
    generated = {".o", ".d", ".dll", ".exe", ".a", ".lib", ".pdb", ".pyc"}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if path.is_file() and not omitted.intersection(relative.parts) and path.suffix.lower() not in generated:
                archive.write(path, relative.as_posix())


def main():
    if DIST.exists():
        raise RuntimeError(f"Refusing to overwrite existing release: {DIST}")
    backup = WORK / "package_previous"
    if backup.exists():
        raise RuntimeError("Previous package already archived; inspect before rebuilding")
    py = ROOT / "tools/.venv_lobby/Scripts/python.exe"
    build = WORK / "lobby_build"
    subprocess.run([str(py), "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
                    "--name", "TM3Lobby", "--distpath", str(build / "dist"), "--workpath", str(build / "work"),
                    "--specpath", str(build), "--paths", str(ROOT / "network"),
                    str(ROOT / "network/lobby_entry.py")], check=True)
    DIST.mkdir(parents=True)
    def copy(source, relative):
        target = DIST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    copy(build / "dist/TM3Lobby.exe", "TM3Lobby.exe")
    copy(ROOT / "network/lobby_portable_config.json", "TM3Lobby.json")
    copy(ROOT / "network/SEMIPRODUCCION_ES.md", "LEEME.md")
    copy(ROOT / "diagnostics/lobby_console_v1/build/Release/TM3Online.exe", "runtime/TM3Online.exe")
    copy(WORK / "core/beetle_psx_cpu175_semiprod.dll", "runtime/cores/beetle_psx_libretro.dll")
    for name in ("TM3_SQRT_MERGE_V4.bin", "TM3_SQRT_MERGE_V4.cue"):
        copy(PACKAGE / "runtime/game" / name, "runtime/game/" + name)
    assert digest(DIST / "runtime/game/TM3_SQRT_MERGE_V4.bin") == "EBAF1EAA5D43DDFD3C88A860F0205482DEDE4EE20AEBE5555B2D65B0A1BFF14C"
    # Only system resources and runtime dependencies; never test saves or logs.
    shutil.copytree(PACKAGE / "runtime/system", DIST / "runtime/system")
    for path in (PACKAGE / "runtime").glob("*.dll"):
        copy(path, "runtime/" + path.name)
    shutil.copytree(PACKAGE / "licenses", DIST / "licenses")
    (DIST / "sources").mkdir()
    source_zip(WORK / "core", DIST / "sources/core_cpu175.zip")
    source_zip(ROOT / "diagnostics/lobby_console_v1/frontend", DIST / "sources/console.zip")
    for name in ("lobby_client.py", "lobby_server.py", "lobby_entry.py", "lobby_portable_config.json",
                 "SEMIPRODUCCION_ES.md"):
        copy(ROOT / "network" / name, "sources/network/" + name)
    copy(Path(__file__), "sources/package_tm3_semiproduction.py")
    copy(WORK / "BUILD_CORE.ps1", "sources/BUILD_CORE.ps1")
    # No personal configuration: defaults include statistics off and native 1x.
    records = [dict(file=str(p.relative_to(DIST)), bytes=p.stat().st_size, sha256=digest(p))
               for p in sorted(DIST.rglob("*")) if p.is_file()]
    manifest = dict(format="TM3_SEMIPRODUCTION_175_V1", date="2026-10-21", cpu_budget_percent=175,
                    diagnostics_enabled=False, game_disc_unchanged=True,
                    validation="Build and startup checks only; no long 175% online gameplay validation",
                    files=records)
    (DIST / "BUILD_MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    # Resolve exact move targets before touching the previous production folder.
    package_path = PACKAGE.resolve(strict=True)
    backup_path = backup.resolve()
    assert package_path.parent == ROOT.resolve() and package_path.name == "TM3Online_Lobby"
    assert backup_path.is_relative_to(WORK.resolve()) and not backup_path.exists()
    shutil.move(str(package_path), str(backup_path))
    shutil.copytree(DIST, PACKAGE)
    archive_path = DIST.with_suffix(".zip")
    if archive_path.exists():
        raise RuntimeError("Refusing to overwrite an existing ZIP")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(DIST.rglob("*")):
            if path.is_file():
                archive.write(path, (Path(DIST.name) / path.relative_to(DIST)).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
    print(json.dumps(dict(package=str(PACKAGE), distribution=str(DIST), zip=str(archive_path),
                          zip_sha256=digest(archive_path), recoverable_previous_package=str(backup_path)), indent=2))


if __name__ == "__main__":
    main()
