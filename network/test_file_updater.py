import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from file_updater import destination,changed_files,apply_plan,sha,validate_manifest,download_files

class FileUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=self.base/'app';self.root.mkdir();self.stage=self.base/'stage';self.stage.mkdir()
    def tearDown(self):self.temp.cleanup()
    def item(self,name,data):
        source=self.stage/str(len(list(self.stage.iterdir())));source.write_bytes(data)
        return dict(path=name,size=len(data),sha256=sha(source),staged=str(source))
    def manifest(self,extra=()):
        return dict(schema=1,version='v0.3.0',files=[self.item('TM3Lobby.exe',b'lobby'),self.item('TM3Update.exe',b'helper'),self.item('VERSION',b'0.3.0'),*extra])
    def test_all_changed_types_and_unchanged_untouched(self):
        extra=[self.item('network/module.py',b'python'),self.item('runtime/core.dll',b'dll'),self.item('licenses/license.txt',b'license')]
        manifest=self.manifest(extra)
        path=self.root/'licenses/license.txt';path.parent.mkdir();path.write_bytes(b'license');stamp=path.stat().st_mtime_ns
        settings=self.root/'runtime/TM3Console.ini';settings.parent.mkdir();settings.write_bytes(b'personal')
        saves=self.root/'userdata';saves.mkdir();(saves/'card.mcr').write_bytes(b'save')
        changed=changed_files(manifest,self.root)
        self.assertNotIn('licenses/license.txt',[i['path'] for i in changed])
        apply_plan(dict(root=str(self.root),files=changed),self.base)
        for item in manifest['files']:self.assertEqual(sha(self.root/item['path']),item['sha256'])
        self.assertEqual(path.stat().st_mtime_ns,stamp)
        self.assertEqual(settings.read_bytes(),b'personal');self.assertEqual((saves/'card.mcr').read_bytes(),b'save')
        self.assertEqual(changed_files(manifest,self.root),[])
    def test_replacement_failure_rolls_back_previous_files(self):
        import os
        first=self.item('first.py',b'new');second=self.item('second.dll',b'newdll')
        (self.root/'first.py').write_bytes(b'old');(self.root/'second.dll').write_bytes(b'olddll')
        replace=os.replace
        def locked(source,target):
            if Path(source).name=='second.dll.tm3-update':raise PermissionError('locked')
            return replace(source,target)
        with patch('file_updater.os.replace',side_effect=locked):
            with self.assertRaises(PermissionError):apply_plan(dict(root=str(self.root),files=[first,second]),self.base)
        self.assertEqual((self.root/'first.py').read_bytes(),b'old')
        self.assertEqual((self.root/'second.dll').read_bytes(),b'olddll')
        self.assertFalse(list(self.root.glob('*.tm3-update')))
    def test_corrupt_stage_changes_nothing(self):
        item=self.item('module.py',b'good');Path(item['staged']).write_bytes(b'bad')
        with self.assertRaises(ValueError):apply_plan(dict(root=str(self.root),files=[item]),self.base)
        self.assertEqual(list(self.root.iterdir()),[])
    def test_unsafe_paths_and_personal_files_blocked(self):
        for name in ('../x','C:/x','/x','runtime/../../x','runtime\\x','userdata/a.py','runtime/TM3Console.ini','assets/game.bin','a:stream','CON','x./a'):
            with self.subTest(name=name),self.assertRaises(ValueError):destination(self.root,name)
    def test_duplicate_case_paths_blocked(self):
        m=self.manifest([self.item('version',b'duplicate')])
        with self.assertRaises(ValueError):validate_manifest(m,self.root)
    def test_manifest_requires_helper_and_lobby(self):
        with self.assertRaises(ValueError):validate_manifest(dict(schema=1,files=[self.item('VERSION',b'1')]),self.root)
    def test_download_only_changed_files(self):
        manifest=self.manifest([self.item('network/module.py',b'new')]);data={i['sha256']:Path(i['staged']).read_bytes() for i in manifest['files']}
        for item in manifest['files']:
            if item['path']!='network/module.py':(self.root/item['path']).write_bytes(data[item['sha256']])
        assets={'tm3-'+i['sha256']:dict(sha256=i['sha256'],size=i['size'],url=i['sha256']) for i in manifest['files']}
        manifest_file=self.stage/'manifest.json';manifest_file.write_text(json.dumps(manifest))
        calls=[]
        def download(asset,cache,progress=None,cancelled=None):
            if asset.get('manifest'):return manifest_file
            calls.append(asset['url']);cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
            target=cache/'file';target.write_bytes(data[asset['sha256']]);return target
        with patch('release_updater.download_installer',side_effect=download):
            result=download_files(dict(version='v0.3.0',manifest={'manifest':True},assets=assets),self.root,self.base/'cache')
        self.assertEqual(result['files'],['network/module.py'])
        self.assertEqual(calls,[manifest['files'][-1]['sha256']])
    def test_duplicate_content_is_fetched_once_for_multiple_paths(self):
        first=self.item('docs/one.txt',b'shared content')
        second=self.item('docs/two.txt',b'shared content')
        manifest=self.manifest([first,second]);data={i['sha256']:Path(i['staged']).read_bytes() for i in manifest['files']}
        assets={'tm3-'+i['sha256']:dict(sha256=i['sha256'],size=i['size'],url=i['sha256']) for i in manifest['files']}
        manifest_file=self.stage/'manifest.json';manifest_file.write_text(json.dumps(manifest))
        calls=[]
        def download(asset,cache,progress=None,cancelled=None):
            if asset.get('manifest'):return manifest_file
            calls.append(asset['sha256']);cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
            target=cache/'file';target.write_bytes(data[asset['sha256']]);return target
        with patch('release_updater.download_installer',side_effect=download):
            result=download_files(dict(version='v0.3.0',manifest={'manifest':True},assets=assets),self.root,self.base/'cache')
        self.assertEqual(calls.count(first['sha256']),1)
        self.assertEqual(result['files'],['TM3Lobby.exe','TM3Update.exe','VERSION','docs/one.txt','docs/two.txt'])
        plan=json.loads(Path(result['plan']).read_text())
        staged={i['path']:i['staged'] for i in plan['files']}
        self.assertEqual(staged['docs/one.txt'],staged['docs/two.txt'])

if __name__=='__main__':unittest.main()

class RecoveryTests(FileUpdateTests):
    def test_recover_interrupted_transaction_before_next_apply(self):
        target=self.root/'module.py';target.write_bytes(b'partial-new')
        backup=self.base/'rollback';backup.mkdir();(backup/'0').write_bytes(b'old')
        (self.base/'transaction.json').write_text(json.dumps(dict(root=str(self.root.resolve()),entries=[dict(path='module.py',index=0,existed=True)])))
        apply_plan(dict(root=str(self.root),files=[self.item('module.py',b'final-new')]),self.base)
        self.assertEqual(target.read_bytes(),b'final-new')
        self.assertFalse((self.base/'transaction.json').exists())
        self.assertFalse(backup.exists())

class WindowsLockTests(FileUpdateTests):
    def test_real_locked_dll_restores_previously_replaced_python(self):
        import ctypes as C
        first=self.item('module.py',b'new');second=self.item('locked.dll',b'newdll')
        (self.root/'module.py').write_bytes(b'old');target=self.root/'locked.dll';target.write_bytes(b'olddll')
        kernel=C.windll.kernel32;kernel.CreateFileW.restype=C.c_void_p
        kernel.CreateFileW.argtypes=[C.c_wchar_p,C.c_uint,C.c_uint,C.c_void_p,C.c_uint,C.c_uint,C.c_void_p];kernel.CloseHandle.argtypes=[C.c_void_p]
        # Permit reads/backups, prohibit replacement and writes to the loaded DLL.
        handle=kernel.CreateFileW(str(target),0x80000000,1,None,3,0,None)
        self.assertNotEqual(handle,C.c_void_p(-1).value)
        try:
            with self.assertRaises(PermissionError):apply_plan(dict(root=str(self.root),files=[first,second]),self.base)
        finally:kernel.CloseHandle(handle)
        self.assertEqual((self.root/'module.py').read_bytes(),b'old');self.assertEqual(target.read_bytes(),b'olddll')
