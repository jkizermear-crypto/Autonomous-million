import copy
import json
import unittest
from pathlib import Path
from tools.experiment_coordinator import run

ROOT = Path(__file__).resolve().parents[1]


class ExperimentCoordinatorTests(unittest.TestCase):
    def setUp(self):
        fixture = json.loads((ROOT / 'tests/fixtures/experiment.json').read_text())
        self.experiment = fixture['experiment']
        self.responses = fixture['responses']
        self.policy = json.loads((ROOT / 'config/experiment-policy.json').read_text())

    def execute(self):
        return run(self.experiment, self.responses, self.policy)

    def test_complete_handoff_never_claims_payment_or_execution(self):
        original = copy.deepcopy(self.responses)
        result = self.execute()
        self.assertEqual(result['status'], 'awaiting_owner_approval')
        self.assertEqual(result['verified_revenue_usd'], 0)
        self.assertEqual(result['turns_used'], 5)
        self.assertTrue(all(x['passed'] for x in result['test_results']))
        self.assertEqual(original, self.responses)

    def test_false_model_pass_cannot_hide_failed_check(self):
        self.responses['builder']['artifact'] = 'Eligibility: only'
        self.responses['tester']['passed'] = True
        self.assertEqual(self.execute()['reason'], 'deliverable_failed_checks')

    def test_unresolved_payout_stops_before_build(self):
        self.responses['researcher']['payment_path'] = 'unknown'
        self.assertEqual(self.execute()['turns_used'], 2)
        self.assertEqual(self.execute()['status'], 'blocked')

    def test_missing_source_provenance_blocks(self):
        del self.responses['researcher']['evidence'][0]['source']
        self.assertEqual(self.execute()['reason'], 'evidence_missing_provenance')

    def test_critic_blocker_stops(self):
        self.responses['critic']['blocking_issues'] = ['Requires purchase']
        self.assertEqual(self.execute()['turns_used'], 3)

    def test_budget_pauses_without_restarting_work(self):
        self.policy['max_role_turns'] = 2
        result = self.execute()
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(len(result['ledger']), 2)

    def test_live_or_paid_policy_rejected(self):
        self.policy['live_model_calls_enabled'] = True
        with self.assertRaises(ValueError):
            self.execute()

    def test_missing_role_blocks(self):
        del self.responses['builder']
        self.assertEqual(self.execute()['reason'], 'missing_or_invalid_builder_output')

    def test_tester_must_cover_planner_criteria(self):
        self.responses['tester']['checks'].pop()
        self.assertEqual(self.execute()['reason'], 'acceptance_coverage_missing')

    def test_changed_artifact_changes_hash(self):
        first = self.execute()['artifact_sha256']
        self.responses['builder']['artifact'] += ' Additional evidence.'
        self.assertNotEqual(first, self.execute()['artifact_sha256'])


if __name__ == '__main__':
    unittest.main()
