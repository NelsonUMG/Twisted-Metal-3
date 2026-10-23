import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
from release_updater import check_update, download_installer, version_tuple, REPOSITORY

class Response(BytesIO):
    def geturl(self): return 'https://release-assets.githubusercontent.com/installer'

class ReleaseUpdaterTests(unittest.TestCase):
    def release(self, **extra):
        asset = dict(name='TM3Online-Setup.exe', digest='sha256:'+'a'*64, size=123,
                     browser_download_url=f'https://github.com/{REPOSITORY}/releases/download/v0.3.0/TM3Online-Setup.exe')
        asset.update(extra)
        return Response(json.dumps(dict(tag_name='v0.3.0', draft=False, prerelease=False, assets=[asset])).encode())

    def test_newer_release(self):
        with patch('release_updater.urlopen', return_value=self.release()):
            self.assertEqual(check_update('0.2.0')['version'], 'v0.3.0')
        with patch('release_updater.urlopen', return_value=self.release()):
            self.assertIsNone(check_update('0.3.0'))

    def test_foreign_urls_and_missing_digest(self):
        for extra in ({'browser_download_url':'https://example.com/evil.exe'}, {'digest':None}):
            with patch('release_updater.urlopen', return_value=self.release(**extra)):
                with self.assertRaises((ValueError, TypeError)): check_update('0.2.0')

    def test_corrupt_download_is_never_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            update = dict(url='https://github.com/test', size=4, sha256=hashlib.sha256(b'good').hexdigest())
            for block in (b'bad!', b'no', b'too-long'):
                with patch('release_updater.urlopen', return_value=Response(block)):
                    with self.assertRaises(ValueError): download_installer(update, directory)
                self.assertFalse((Path(directory)/'TM3Online-Setup.exe').exists())
            with patch('release_updater.urlopen', return_value=Response(b'good')):
                self.assertEqual(download_installer(update, directory).read_bytes(), b'good')

    def test_versions_compare_numerically(self):
        self.assertGreater(version_tuple('v0.10.0'), version_tuple('0.9.0'))
        with self.assertRaises(ValueError): version_tuple('../../evil')

if __name__ == '__main__': unittest.main()
