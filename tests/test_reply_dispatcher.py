import copy
import datetime
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import moltbook_coordinator as c
import reply_dispatcher as d


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'source', 'author': {'id': 'agent', 'name': 'Agent'},
                       'parent_id': 'root', 'content': 'VOLUNTEER: research\nIDEA: documentation', 'replies': []}
        self.comments = [{'id': 'root', 'author': {'name': c.OWN_NAME}, 'replies': [self.source]}]
        state = json.loads((ROOT / 'coordination-state.json').read_text())
        state['conversations'] = []
        for key in ['drafts', 'experiments', 'collaborators', 'processed_comments', 'reply_attempts']:
            state[key] = {}
        c.register(state, 'post', 'root')
        self.state, _ = c.process(state, lambda path: {'comments': self.comments, 'has_more': False}, 'live')
        self.policy = json.loads((ROOT / 'config/reply-policy.json').read_text())
        self.policy.update(enabled=True, standing_public_reply_approval=True, allowed_post_ids=['post'])
        self.events = []
        self.saved = []

    def persist(self, state):
        self.events.append('persist')
        self.saved.append(copy.deepcopy(state))

    def api(self, method, path, data=None):
        self.events.append(method)
        if method == 'GET':
            return {'comments': self.comments, 'has_more': False}
        self.assertEqual(self.events[-2], 'persist')
        return {'success': True, 'comment': {'id': 'reply', 'verification_status': 'approved'}}

    def test_disabled_policy_makes_no_requests(self):
        self.policy['enabled'] = False
        state, report = d.dispatch(self.state, self.policy, self.api, self.persist, True)
        self.assertEqual(report['action'], 'disabled_by_policy')
        self.assertEqual(self.events, [])

    def test_preview_rechecks_without_writes_or_state_commits(self):
        state, report = d.dispatch(self.state, self.policy, self.api, self.persist)
        self.assertEqual(len(report['candidates']), 1)
        self.assertEqual(self.events, ['GET'])
        self.assertFalse(report['publishing_enabled'])

    def test_one_reply_then_rerun_is_idempotent(self):
        state, report = d.dispatch(self.state, self.policy, self.api, self.persist, True)
        self.assertEqual(report['action'], 'reply_sent_verified')
        self.assertEqual(self.events.count('POST'), 1)
        self.assertEqual(self.saved[0]['reply_attempts']['post:source']['status'], 'attempting')
        d.dispatch(state, self.policy, self.api, self.persist, True)
        self.assertEqual(self.events.count('POST'), 1)

    def test_failed_post_has_durable_marker(self):
        def api(method, path, data=None):
            if method == 'GET': return {'comments': self.comments, 'has_more': False}
            raise OSError('uncertain network outcome')
        with self.assertRaises(OSError):
            d.dispatch(self.state, self.policy, api, self.persist, True)
        self.assertEqual(self.saved[-1]['reply_attempts']['post:source']['status'], 'attempting')
        state, report = d.dispatch(self.saved[-1], self.policy, self.api, self.persist, True)
        self.assertEqual(self.events.count('POST'), 0)

    def test_known_verification_is_completed_without_gemini(self):
        checkpoints = []
        def api(method, path, data=None):
            if method == 'GET': return {'comments': self.comments, 'has_more': False}
            if path == '/verify':
                self.assertEqual(data['answer'], '96.00')
                return {'success': True}
            return {'success': True, 'comment': {'id': 'reply', 'verification_status': 'pending',
                    'verification': {'verification_code': 'fixture-code',
                                     'challenge_text': 'A] LoO bS tErS^ C lA w- FoR cE } iS^ tHiRrTy TtW o } nE wTo Ns ~ aNd^ iTs- MoL tI nG / MaKeS iT TrIiPlEe | hOw^ MuCh- ToTaL } FoR cE< ?'}}}
        state, report = d.dispatch(self.state, self.policy, api, self.persist, True, checkpoint=checkpoints.append)
        self.assertEqual(report['action'], 'reply_verified')
        self.assertEqual(report['moltbook_writes'], 2)
        self.assertEqual(report['gemini_calls'], 0)
        self.assertEqual(state['reply_attempts']['post:source']['status'], 'verified')
        self.assertEqual(len(checkpoints), 1)

    def test_ambiguous_verification_is_preserved_without_guessing(self):
        def api(method, path, data=None):
            if method == 'GET': return {'comments': self.comments, 'has_more': False}
            self.assertNotEqual(path, '/verify')
            return {'success': True, 'comment': {'id': 'reply', 'verification_status': 'pending',
                    'verification': {'verification_code': 'fixture', 'challenge_text': 'two or three?'}}}
        state, report = d.dispatch(self.state, self.policy, api, self.persist, True)
        self.assertEqual(report['action'], 'verification_needs_review')
        self.assertEqual(state['reply_attempts']['post:source']['status'], 'verification_pending')

    def test_fresh_withdrawal_changed_source_and_incomplete_scan_block_posts(self):
        cases = [
            lambda: self.comments.append({'id': 'withdraw', 'author': {'name': 'Agent'}, 'content': 'WITHDRAW:', 'replies': []}),
            lambda: self.source.update(content='Changed after drafting'),
        ]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                original = copy.deepcopy(self.comments)
                mutate()
                state, report = d.dispatch(self.state, self.policy, self.api, self.persist, True)
                self.assertEqual(report['moltbook_writes'], 0)
                self.comments[:] = original
                self.source = self.comments[0]['replies'][0]
        state, report = d.dispatch(self.state, self.policy,
            lambda *args: {'comments': self.comments, 'has_more': True}, self.persist, True)
        self.assertEqual(report['moltbook_writes'], 0)

    def test_existing_reply_reconciles_uncertain_attempt(self):
        self.state['reply_attempts'] = {'post:source': {'status': 'attempting', 'post_id': 'post',
            'parent_id': 'source', 'agent_key': 'agent', 'attempted_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}}
        text = self.state['drafts']['post:source']['content']
        self.source['replies'] = [{'id': 'own', 'author': {'name': c.OWN_NAME}, 'content': text, 'replies': []}]
        state, report = d.dispatch(self.state, self.policy, self.api, self.persist, True)
        self.assertEqual(state['reply_attempts']['post:source']['status'], 'verified')
        self.assertEqual(report['moltbook_writes'], 0)

    def test_modified_or_simulated_drafts_are_not_sent(self):
        for field, value in [('content', 'An unapproved arbitrary message'), ('source', 'fixtures')]:
            state = copy.deepcopy(self.state)
            state['drafts']['post:source'][field] = value
            _, report = d.dispatch(state, self.policy, self.api, self.persist, True)
            self.assertEqual(report['moltbook_writes'], 0)

    def test_multiple_candidates_still_send_at_most_one(self):
        second = copy.deepcopy(self.source)
        second['id'] = 'second'
        second['author'] = {'id': 'other', 'name': 'Other'}
        self.comments[0]['replies'].append(second)
        state, _ = c.process(self.state, lambda path: {'comments': self.comments, 'has_more': False}, 'live')
        state, report = d.dispatch(state, self.policy, self.api, self.persist, True)
        self.assertEqual(self.events.count('POST'), 1)
        self.assertEqual(sum(a['status'] == 'verified' for a in state['reply_attempts'].values()), 1)

    def test_author_cooldown_and_pending_source_block_posts(self):
        self.state['reply_attempts'] = {'post:older': {'status': 'verified', 'agent_key': 'agent',
            'attempted_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}}
        _, report = d.dispatch(self.state, self.policy, self.api, self.persist, True)
        self.assertEqual(report['moltbook_writes'], 0)
        self.state['reply_attempts'] = {}
        self.source['verificationStatus'] = 'pending'
        _, report = d.dispatch(self.state, self.policy, self.api, self.persist, True)
        self.assertEqual(report['moltbook_writes'], 0)

    def test_math_grammar(self):
        for question, answer in [('2 plus 3', '5.00'), ('ten minus four', '6.00'),
                                 ('6 divided by 2', '3.00'), ('three multiplied by seven', '21.00'),
                                 ('force thirty two tripled', '96.00')]:
            with self.subTest(question=question): self.assertEqual(d.solve_arithmetic(question), answer)
        for question in ['2 plus 3 minus 1', '2 and 3', '4 plus 5 and 6', '5 divided by zero',
                         '4 and 2 tripled', '-2 plus 3', '.5 plus 2', '1/2 plus 3', 'subtract ten from twenty']:
            with self.subTest(question=question), self.assertRaises(ValueError): d.solve_arithmetic(question)


if __name__ == '__main__': unittest.main()
