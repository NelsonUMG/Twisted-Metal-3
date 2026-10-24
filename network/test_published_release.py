import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('check_published_release',
    Path(__file__).resolve().parents[1] / 'tools/check_published_release.py')
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


class PublishedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.digest = 'a' * 64
        self.manifest = {'version': 'v0.2.2', 'files': [
            {'path': 'TM3Lobby.exe', 'size': 100, 'sha256': self.digest}]}
        self.release = {'tag_name': 'v0.2.2', 'assets': [
            {'name': 'TM3Online-update.json'},
            {'name': 'tm3-' + self.digest, 'size': 100, 'digest': 'sha256:' + self.digest}]}

    def test_complete_publication_is_accepted_without_changing_it(self):
        publication.validate(self.release, self.manifest, 'v0.2.2')
        self.assertEqual(len(self.release['assets']), 2)

    def test_incomplete_or_altered_asset_is_rejected(self):
        self.release['assets'][1]['size'] = 99
        with self.assertRaises(ValueError):
            publication.validate(self.release, self.manifest, 'v0.2.2')
        self.release['assets'].pop()
        with self.assertRaises(ValueError):
            publication.validate(self.release, self.manifest, 'v0.2.2')

    def test_extra_installer_is_rejected(self):
        self.release['assets'].append({'name': 'installer.msi'})
        with self.assertRaises(ValueError):
            publication.validate(self.release, self.manifest, 'v0.2.2')

    def test_wrong_version_is_rejected(self):
        with self.assertRaises(ValueError):
            publication.validate(self.release, self.manifest, 'v0.2.3')
