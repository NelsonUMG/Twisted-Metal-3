"""Audit isolated RAM experiment; never copy it into the playable portable."""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'diagnostics/ram256_v1'
SOURCE = ROOT / 'third_party/beetle-psx-libretro-c27ab27c05569575e04b25e03e87fe3220fde599'


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest().upper()


def main():
    guest = json.loads((OUT / 'guest_checkpoint.json').read_text())
    game = json.loads((OUT / 'tm3_checkpoint.json').read_text())
    for report in (guest, game):
        assert report['ram_bytes'] == 268435456
        assert report['ram_restored'] and report['boot_replay_ram_equal']
        assert report['extension_restore_checked']
    assert guest['guest_cpu_access_and_execute_passed']
    assert guest['test_entry_hook_used'] and not game['test_entry_hook_used']
    assert game['game_executable_loaded']
    assert not game['linked_gameplay_tested']
    original = (SOURCE / 'libretro.c').read_text(encoding='utf-8')
    modified = (OUT / 'core/libretro.c').read_text(encoding='utf-8')
    (OUT / 'core_changes.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), modified.splitlines(True),
        fromfile='original/libretro.c', tofile='ram256/libretro.c')), encoding='utf-8')
    manifest = json.loads((ROOT / 'TM3Online_Lobby/BUILD_MANIFEST.json').read_text())
    preserved = []
    for entry in manifest['files']:
        relative = entry['file'].replace('\\', '/')
        if relative.startswith('runtime/') or relative == 'TM3Lobby.exe':
            assert digest(ROOT / 'TM3Online_Lobby' / relative) == entry['sha256'].upper(), relative
            preserved.append(relative)
    report = dict(passed=True, experimental_ram_bytes=268435456,
        original_core_source_sha256=digest(SOURCE / 'libretro.c'),
        modified_core_source_sha256=digest(OUT / 'core/libretro.c'),
        experimental_core_sha256=digest(OUT / 'core/mednafen_psx_libretro.dll'),
        protected_installed_files=preserved, production_files_preserved=True,
        new_internet_engine_complete=False, linked_gameplay_validated=False,
        raw_guest_bios_boot_validated=False, game_code_loaded_with_new_core=True,
        dma_extended=False, jit_supported=False)
    source_manifest = json.loads((OUT / 'source_manifest.json').read_text())
    source_manifest['prepared_source_sha256_before_qa_hook'] = source_manifest.pop('candidate_sha256') if 'candidate_sha256' in source_manifest else source_manifest['prepared_source_sha256_before_qa_hook']
    source_manifest['final_source_sha256'] = report['modified_core_source_sha256']
    source_manifest['final_dll_sha256'] = report['experimental_core_sha256']
    source_manifest['local_qa_entry_hook_included'] = True
    (OUT / 'source_manifest.json').write_text(json.dumps(source_manifest, indent=2), encoding='utf-8')
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
