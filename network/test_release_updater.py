import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
from urllib.error import URLError
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

    def test_021_detects_023_as_a_valid_upgrade(self):
        response = Response(json.dumps(dict(tag_name='v0.2.3', draft=False,
            prerelease=False, assets=[dict(name='TM3Online-Setup.exe',
            digest='sha256:'+'a'*64, size=123,
            browser_download_url=f'https://github.com/{REPOSITORY}/releases/download/v0.2.3/TM3Online-Setup.exe')])).encode())
        with patch('release_updater.urlopen', return_value=response):
            self.assertEqual(check_update('0.2.1')['version'], 'v0.2.3')

    def test_release_check_retries_a_transient_timeout(self):
        with patch('release_updater.urlopen', side_effect=[
                URLError(TimeoutError('connection timed out')), self.release()]) as opened, \
                patch('release_updater.time.sleep'):
            self.assertEqual(check_update('0.2.0')['version'], 'v0.3.0')
        self.assertEqual(opened.call_count, 2)

    def test_network_timeout_is_retried_then_download_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            update = dict(url='https://github.com/test', size=4,
                          sha256=hashlib.sha256(b'good').hexdigest())
            with patch('release_updater.urlopen', side_effect=[
                    URLError(TimeoutError('connection timed out')), Response(b'good')]) as opened, \
                    patch('release_updater.time.sleep'):
                target = download_installer(update, directory)
            self.assertEqual(opened.call_count, 2)
            self.assertEqual(target.read_bytes(), b'good')
            self.assertFalse((Path(directory)/'TM3Online-Setup.exe.partial').exists())

    def test_verified_cached_file_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            cached=Path(directory)/'TM3Online-Setup.exe';cached.write_bytes(b'good')
            update=dict(url='https://github.com/test',size=4,
                        sha256=hashlib.sha256(b'good').hexdigest())
            with patch('release_updater.urlopen',side_effect=AssertionError('network should not be used')):
                self.assertEqual(download_installer(update,directory),cached)

    def test_corrupt_cached_file_is_redownloaded_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            cached=Path(directory)/'TM3Online-Setup.exe';cached.write_bytes(b'bad!')
            update=dict(url='https://github.com/test',size=4,
                        sha256=hashlib.sha256(b'good').hexdigest())
            with patch('release_updater.urlopen',return_value=Response(b'good')) as opened:
                self.assertEqual(download_installer(update,directory).read_bytes(),b'good')
            self.assertEqual(opened.call_count,1)

    def test_network_failure_reports_exhausted_attempts_and_keeps_no_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            update = dict(url='https://github.com/test', size=4,
                          sha256=hashlib.sha256(b'good').hexdigest())
            with patch('release_updater.urlopen', side_effect=URLError(TimeoutError('10060'))), \
                    patch('release_updater.time.sleep'):
                with self.assertRaisesRegex(URLError, '4 intentos'):
                    download_installer(update, directory)
            self.assertFalse((Path(directory)/'TM3Online-Setup.exe.partial').exists())
            self.assertFalse((Path(directory)/'TM3Online-Setup.exe').exists())

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
