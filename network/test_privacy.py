import unittest
from privacy import public_text, public_diagnostic


class PrivacyTests(unittest.TestCase):
    def test_network_errors_hide_service_and_credentials(self):
        message = ('Failed https://owner.workers.dev/api?secret=private '
                   'owner.pages.dev Authorization: Bearer abc.def '
                   'api_token="private-token" account_id=account123')
        cleaned = public_text(message)
        for hidden in ('owner', 'private', 'abc.def', 'account123', 'workers.dev'):
            self.assertNotIn(hidden, cleaned)
        self.assertIn('Failed', cleaned)

    def test_nested_diagnostics_keep_measurements_without_secrets(self):
        report = {'rtt_ms': 23, 'ice': {'token': 'secret-value',
                  'error': 'Failed wss://owner.workers.dev/socket'},
                  'events': [{'account_id': 'private-account'}]}
        cleaned = public_diagnostic(report)
        self.assertEqual(cleaned['rtt_ms'], 23)
        self.assertNotIn('secret-value', str(cleaned))
        self.assertNotIn('private-account', str(cleaned))
        self.assertNotIn('owner', str(cleaned))
        self.assertEqual(report['ice']['token'], 'secret-value')

    def test_normal_player_text_is_preserved(self):
        self.assertEqual(public_text('Esperando jugador. Ping: 20 ms'),
                         'Esperando jugador. Ping: 20 ms')
