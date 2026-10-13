import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import publish_recruitment as p


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.state = json.loads((ROOT / 'coordination-state.json').read_text())
        self.publication = {'status': 'approved', 'approved_sha256': p.APPROVED_SHA256, 'post_id': None}
        self.draft = (ROOT / 'drafts/moltbook-recruitment.md').read_bytes()
        self.events = []

    def persist(self, publication, state, message):
        self.events.append(('persist', publication['status']))

    def test_exact_draft_and_durable_marker_precede_post(self):
        def request(method, path, data):
            self.events.append(('request', path))
            self.assertEqual(self.events[0], ('persist', 'attempting'))
            header, body = self.draft.decode().split('\n\n', 1)
            self.assertEqual(data, {'submolt_name': 'general', 'title': header[2:], 'content': body.strip()})
            return {'success': True, 'post': {'id': 'posted', 'verification_status': 'approved'}}
        report, recovery = p.perform('publish', self.publication, self.state, self.draft,
                                     request=request, persist=self.persist)
        self.assertEqual(report['action'], 'verified')
        self.assertEqual(self.state['conversations'][-1]['post_id'], 'posted')
        self.assertIsNone(recovery)
        self.assertEqual(report['gemini_calls'], 0)

    def test_rerun_cannot_post_again(self):
        self.publication['status'] = 'attempting'
        def forbidden(*args):
            self.fail('Rerun must never repeat a posting attempt')
        report, _ = p.perform('publish', self.publication, self.state, self.draft,
                              request=forbidden, persist=forbidden)
        self.assertEqual(report['action'], 'skipped_existing_attempt')

    def test_modified_draft_cannot_be_published(self):
        with self.assertRaises(ValueError):
            p.perform('publish', self.publication, self.state, self.draft + b'changed',
                      request=lambda *args: self.fail('Unapproved draft must not be sent'), persist=self.persist)
        self.assertEqual(self.events, [])

    def test_uncertain_network_attempt_stays_blocked(self):
        def request(*args):
            raise OSError('Network outcome unknown')
        with self.assertRaises(OSError):
            p.perform('publish', self.publication, self.state, self.draft,
                      request=request, persist=self.persist)
        self.assertEqual(self.publication['status'], 'attempting')

    def test_pending_verification_and_matching_recovery(self):
        response = {'success': True, 'post': {'id': 'posted', 'verification_status': 'pending',
                    'verification': {'verification_code': 'fixture-code', 'challenge_text': '2 + 3'}}}
        report, recovery = p.perform('publish', self.publication, self.state, self.draft,
                                     request=lambda *args: response, persist=self.persist)
        self.assertEqual(report['action'], 'verification_pending')
        self.assertNotIn('verification_code', report)
        self.assertEqual(self.state['conversations'][-1]['verification'], 'pending')
        def verify(method, path, data):
            self.assertEqual(path, '/verify')
            self.assertEqual(data, {'verification_code': 'fixture-code', 'answer': '5.00'})
            return {'success': True}
        report, _ = p.perform('verify', self.publication, self.state, self.draft,
                              request=verify, persist=self.persist, recovery=recovery, answer='5.00')
        self.assertEqual(report['action'], 'verified')
        self.assertEqual(self.state['conversations'][-1]['verification'], 'confirmed')

    def test_wrong_recovery_cannot_verify(self):
        self.publication.update(status='verification_pending', post_id='posted')
        with self.assertRaises(ValueError):
            p.perform('verify', self.publication, self.state, self.draft,
                      request=lambda *args: self.fail('Mismatched recovery must not be used'),
                      recovery={'post_id': 'different', 'approved_sha256': p.APPROVED_SHA256}, answer='5.00')


if __name__ == '__main__':
    unittest.main()
