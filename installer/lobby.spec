from pathlib import Path
root = Path(SPECPATH).parent
a = Analysis([str(root/'network/lobby_entry.py')], pathex=[str(root/'network'), str(root/'256mb system/src')], binaries=[], datas=[], hiddenimports=['release_updater', 'update_window', 'file_updater'], hookspath=[], runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='TM3Lobby', debug=False, strip=False, upx=False, console=False)
