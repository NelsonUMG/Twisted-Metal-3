from pathlib import Path
root = Path(SPECPATH).parent
analysis = Analysis([str(root/'network/file_updater.py')], pathex=[str(root/'network')], binaries=[], datas=[], hiddenimports=[], hookspath=[], runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, [], name='TM3Update', debug=False, strip=False, upx=False, console=False)
