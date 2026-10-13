"""Bounded offline experiment coordinator. No network, model or publishing calls."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROLES = ('planner', 'researcher', 'critic', 'builder', 'tester')
REQUIRED = {
    'planner': ('hypothesis', 'deliverable', 'acceptance_criteria', 'stop_condition'),
    'researcher': ('evidence', 'eligibility', 'payment_path'),
    'critic': ('risks', 'blocking_issues'),
    'builder': ('artifact',),
    'tester': ('checks',),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def run(experiment, responses, policy):
    """Consume separately authored role outputs; approval never follows model agreement."""
    if policy.get('additional_spending_usd') != 0 or policy.get('live_model_calls_enabled') is not False:
        raise ValueError('This runner only supports offline, zero-additional-spending evaluation')
    if not experiment.get('id') or not experiment.get('objective'):
        raise ValueError('Experiment requires id and objective')
    state = copy.deepcopy(experiment)
    state.update(status='running', turns_used=0, ledger=[], additional_spending_usd=0)
    previous = None
    for role in ROLES:
        if state['turns_used'] >= policy['max_role_turns']:
            state.update(status='paused', reason='turn_budget_exhausted')
            return state
        output = responses.get(role)
        if not isinstance(output, dict) or any(not output.get(k) for k in REQUIRED[role] if k != 'blocking_issues'):
            state.update(status='blocked', reason='missing_or_invalid_' + role + '_output')
            return state
        if role == 'critic' and not isinstance(output.get('blocking_issues'), list):
            state.update(status='blocked', reason='invalid_blocking_issues')
            return state
        record = {'role': role, 'owner': 'offline_fixture:' + role,
                  'input_sha256': digest({'experiment': experiment, 'previous': previous}),
                  'output_sha256': digest(output), 'output': copy.deepcopy(output)}
        state['ledger'].append(record)
        state['turns_used'] += 1
        previous = output
        if role == 'researcher':
            evidence = output['evidence']
            if not isinstance(evidence, list) or not evidence or any(
                not isinstance(e, dict) or not all(e.get(k) for k in ('source', 'claim', 'retrieved_at')) for e in evidence):
                state.update(status='blocked', reason='evidence_missing_provenance')
                return state
            if output['eligibility'] != 'confirmed' or output['payment_path'] != 'confirmed':
                state.update(status='blocked', reason='eligibility_or_payment_unresolved')
                return state
        if role == 'critic' and output['blocking_issues']:
            state.update(status='blocked', reason='critic_found_blockers')
            return state
        if role == 'tester':
            artifact = responses['builder']['artifact']
            if not isinstance(artifact, str):
                state.update(status='blocked', reason='artifact_must_be_text')
                return state
            # Deterministic checks evaluated here, rather than trusting a model's pass flag.
            criteria = responses['planner']['acceptance_criteria']
            checks = output['checks']
            if not isinstance(criteria, list) or not isinstance(checks, list) or len(checks) != len(criteria):
                state.update(status='blocked', reason='acceptance_coverage_missing')
                return state
            results = []
            for criterion, check in zip(criteria, checks):
                if not isinstance(check, dict) or check.get('criterion') != criterion or check.get('kind') != 'contains' or not isinstance(check.get('value'), str) or not check['value']:
                    state.update(status='blocked', reason='unsupported_or_mismatched_check')
                    return state
                results.append({'criterion': criterion, 'passed': check['value'] in artifact})
            state['test_results'] = results
            state['artifact_sha256'] = hashlib.sha256(artifact.encode()).hexdigest()
            if not all(r['passed'] for r in results):
                state.update(status='blocked', reason='deliverable_failed_checks')
                return state
    state.update(status='awaiting_owner_approval', reason='offline_checks_passed_not_submitted',
                 revenue_status='unverified', verified_revenue_usd=0)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--policy', default='config/experiment-policy.json')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    fixture = json.loads(Path(args.fixture).read_text())
    result = run(fixture['experiment'], fixture['responses'], json.loads(Path(args.policy).read_text()))
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
