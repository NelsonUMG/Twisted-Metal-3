"""Installer artifacts must never enter file-update releases."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tm3_build_update_assets',ROOT/'tools/build_update_assets.py')
packaging=importlib.util.module_from_spec(spec);spec.loader.exec_module(packaging)

class ReleasePackagingTests(unittest.TestCase):
    def payload(self,folder):
        payload=Path(folder)/'payload';payload.mkdir()
        for name,data in (('TM3Lobby.exe',b'lobby'),('TM3Update.exe',b'helper'),('VERSION',b'0.2.1')):
            (payload/name).write_bytes(data)
        return payload
    def test_normal_application_files_are_published(self):
        with tempfile.TemporaryDirectory() as folder:
            payload=self.payload(folder);output=Path(folder)/'release'
            manifest=packaging.build(payload,output,'0.2.1')
            self.assertEqual(len(manifest['files']),3)
            self.assertTrue((output/'TM3Online-update.json').is_file())
    def test_installers_and_installer_debug_files_are_rejected(self):
        for name in ('setup.msi','installer.MSI','setup.msp','data.msm','build.wixpdb','build.wixobj','build.wixlib','TM3Online-Setup.exe'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                payload=self.payload(folder);(payload/name).write_bytes(b'not an application update')
                output=Path(folder)/'release'
                with self.assertRaises(ValueError):packaging.build(payload,output,'0.2.1')
                self.assertFalse((output/'TM3Online-update.json').exists())

if __name__=='__main__':unittest.main()
