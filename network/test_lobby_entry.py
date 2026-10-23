import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import lobby_entry

class EngineFailureTests(unittest.TestCase):
    def test_engine_initialization_error_becomes_session_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)/'state.json'
            runtime = SimpleNamespace(main=Mock(side_effect=RuntimeError('audio device unavailable')))
            with patch.dict('sys.modules', {'system256_runtime': runtime}), patch('sys.argv', ['TM3Lobby', '--system256', '--state', str(state)]):
                self.assertEqual(lobby_entry.main(), 1)
            saved = json.loads(state.read_text())
            self.assertEqual(saved['state'], 'failed')
            self.assertEqual(saved['error'], 'audio device unavailable')
            self.assertIn('audio device unavailable', Path(saved['error_log']).read_text(encoding='utf-8-sig'))

    def test_existing_runtime_error_is_preserved_without_unhandled_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)/'state.json'
            original = dict(state='failed', error='peer disconnected', error_log='original log')
            state.write_text(json.dumps(original))
            runtime = SimpleNamespace(main=Mock(side_effect=RuntimeError('peer disconnected')))
            with patch.dict('sys.modules', {'system256_runtime': runtime}), patch('sys.argv', ['TM3Lobby', '--system256', '--state', str(state)]):
                self.assertEqual(lobby_entry.main(), 1)
            self.assertEqual(json.loads(state.read_text()), original)

if __name__ == '__main__': unittest.main()
