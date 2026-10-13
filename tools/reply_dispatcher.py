"""Preview or dispatch one authorized reply; public execution is disabled by policy."""
import argparse
import copy
import datetime
from decimal import Decimal
import hashlib
import json
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.request

from moltbook_coordinator import OWN_NAME, author, draft_text, fields, parent, read_comments, register


def normalized(text):
    return re.sub(r'([a-z])\1+', r'\1', re.sub(r'[^a-z0-9.]', '', text.lower()))


def solve_arithmetic(challenge):
    """Recognize a restricted arithmetic grammar; ambiguous questions require review."""
    units = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
             'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
             'seventeen', 'eighteen', 'nineteen']
    tens = ['twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
    words = {normalized(word): Decimal(i) for i, word in enumerate(units)}
    for i, word in enumerate(tens, 2):
        words[normalized(word)] = Decimal(i * 10)
        for j in range(1, 10):
            words[normalized(word + units[j])] = Decimal(i * 10 + j)
    text = normalized(challenge)
    # Numeric negatives, exponent notation, and leading decimals are outside this grammar.
    if re.search(r'-\s*\d|\d[eE][+-]?\d|(?<!\d)\.\d|\d\s*/\s*\d', challenge):
        raise ValueError('Unsupported numeric notation')
    tokens = re.findall(r'\d+(?:\.\d+)?|' + '|'.join(sorted(words, key=len, reverse=True)), text)
    numbers = [words[t] if t in words else Decimal(t) for t in tokens]
    operations = []
    for name, expressions in [('add', ['plus', 'addedto']), ('subtract', ['minus']),
                              ('multiply', ['multipliedby', 'times']), ('divide', ['dividedby'])]:
        if any(normalized(expression) in text for expression in expressions):
            operations.append((name, None))
    for expression, factor in [('double', 2), ('triple', 3)]:
        if normalized(expression) in text:
            operations.append(('multiply', Decimal(factor)))
    if len(operations) != 1:
        raise ValueError('Arithmetic operation is ambiguous')
    operation, factor = operations[0]
    if factor is not None:
        if len(numbers) != 1:
            raise ValueError('Multiplier operands are ambiguous')
        numbers.append(factor)
    if len(numbers) != 2 or any(n < 0 or n > 10000 for n in numbers):
        raise ValueError('Arithmetic operands are ambiguous')
    a, b = numbers
    if operation == 'add': result = a + b
    elif operation == 'subtract': result = a - b
    elif operation == 'multiply': result = a * b
    elif b != 0: result = a / b
    else: raise ValueError('Division by zero')
    if not result.is_finite() or abs(result) > 1000000000:
        raise ValueError('Unreasonable arithmetic result')
    return format(result, '.2f')


class MoltbookAPI:
    def __init__(self, key='', writes=False):
        self.key, self.writes = key, writes

    def __call__(self, method, path, data=None):
        read = method == 'GET' and re.fullmatch(r'/posts/[A-Za-z0-9-]+/comments\?.+', path)
        write = method == 'POST' and (path == '/verify' or re.fullmatch(r'/posts/[A-Za-z0-9-]+/comments', path))
        if not read and not (write and self.writes and self.key):
            raise ValueError('Moltbook operation is not enabled')
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        request = urllib.request.Request('https://www.moltbook.com/api/v1' + path,
            method=method, headers=headers, data=json.dumps(data).encode() if data is not None else None)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=50) as response:
            return json.load(response)


def dispatch(state, policy, api, persist, execute=False, recovery=None, checkpoint=None, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    state = copy.deepcopy(state)
    report = {'timestamp': now.isoformat(), 'publishing_enabled': False, 'action': 'preview_only',
              'gemini_calls': 0, 'moltbook_writes': 0, 'candidates': [], 'skipped': []}
    if execute and not (policy.get('enabled') is True and policy.get('standing_public_reply_approval') is True):
        report['action'] = 'disabled_by_policy'
        return state, report
    report['publishing_enabled'] = bool(execute)
    if policy.get('max_replies_per_run') != 1 or policy.get('gemini_calls_allowed') is not False:
        raise ValueError('Only one reply and zero Gemini calls are supported')
    attempts = state.setdefault('reply_attempts', {})
    report['pending_verifications'] = [key for key, value in attempts.items() if value.get('status') == 'verification_pending']
    # Resume a known verification only; never resubmit a comment after an uncertain POST.
    if execute and recovery:
        key = recovery.get('draft_key')
        attempt = attempts.get(key, {})
        if attempt.get('status') != 'verification_pending' or attempt.get('comment_id') != recovery.get('comment_id'):
            report['action'] = 'skipped_unmatched_recovery'
            return state, report
        if attempt.get('post_id') not in policy.get('allowed_post_ids', []):
            report['action'] = 'skipped_recovery_outside_policy'
            return state, report
        try:
            answer = solve_arithmetic(recovery['challenge_text'])
        except ValueError:
            report['action'] = 'verification_needs_review'
            return state, report
        result = api('POST', '/verify', {'verification_code': recovery['verification_code'], 'answer': answer})
        report['moltbook_writes'] += 1
        if result.get('success') is not True:
            report['action'] = 'verification_not_confirmed'
            return state, report
        attempt['status'] = 'verified'
        state['drafts'][key]['status'] = 'sent_verified'
        register(state, attempt['post_id'], attempt['comment_id'], source='authorized_dispatcher')
        persist(state)
        report.update(action='reply_verified', publishing_enabled=True, comment_id=attempt['comment_id'])
        return state, report
    scans = {}
    # A timed-out POST may have succeeded. Reconcile visible own replies before
    # considering new work, but never repeat an uncertain comment submission.
    for key, attempt in attempts.items():
        if attempt.get('status') != 'attempting':
            continue
        draft = state['drafts'].get(key)
        if not draft or attempt.get('post_id') not in policy.get('allowed_post_ids', []):
            continue
        pid = attempt['post_id']
        if pid not in scans:
            scans[pid] = read_comments(lambda path: api('GET', path), pid)
        comments, diagnostics = scans[pid]
        matches = [c for c in comments if author(c).lower() == OWN_NAME and parent(c) == attempt['parent_id']
                   and str(c.get('content', '')).strip() == draft['content'].strip() and not c.get('is_deleted')]
        if diagnostics['complete'] and len(matches) == 1 and matches[0].get('verification_status', matches[0].get('verificationStatus')) != 'pending':
            attempt.update(status='verified', comment_id=str(matches[0]['id']))
            draft['status'] = 'sent_verified'
            register(state, pid, attempt['comment_id'], source='reconciled_dispatcher')
        else:
            report['skipped'].append({'draft_key': key, 'reason': 'uncertain_attempt_requires_review'})
    for key, draft in sorted(state.get('drafts', {}).items()):
        if draft.get('status') != 'awaiting_approval' or key in attempts:
            continue
        pid, cid, agent_key = draft['post_id'], draft['parent_id'], draft['agent_key']
        participant = state['collaborators'].get(agent_key, {})
        reason = None
        if pid not in policy.get('allowed_post_ids', []): reason = 'outside_allowed_threads'
        elif draft.get('kind') not in policy.get('allowed_kinds', []): reason = 'requires_individual_review'
        elif participant.get('participation') == 'withdrawn': reason = 'participant_withdrew'
        elif policy.get('require_opt_in') and participant.get('participation') != 'opted_in': reason = 'no_explicit_opt_in'
        elif draft.get('source') != 'live': reason = 'simulated_draft'
        elif draft.get('content') != draft_text(draft['kind'], {}): reason = 'draft_outside_template_policy'
        for attempt in attempts.values():
            if attempt.get('agent_key') == agent_key:
                age = now - datetime.datetime.fromisoformat(attempt['attempted_at'])
                if age.total_seconds() < policy.get('author_cooldown_hours', 24) * 3600:
                    reason = 'author_cooldown'
        if reason:
            report['skipped'].append({'draft_key': key, 'reason': reason})
            continue
        if pid not in scans:
            scans[pid] = read_comments(lambda path: api('GET', path), pid)
        comments, diagnostics = scans[pid]
        source = next((c for c in comments if str(c['id']) == cid), None)
        if not diagnostics['complete'] or source is None or source.get('is_deleted') or source.get('verification_status', source.get('verificationStatus')) == 'pending':
            report['skipped'].append({'draft_key': key, 'reason': 'incomplete_or_missing_source'})
            continue
        own = [c for c in comments if author(c).lower() == OWN_NAME and parent(c) == cid and not c.get('is_deleted')]
        if own:
            draft['status'] = 'reply_observed'
            report['skipped'].append({'draft_key': key, 'reason': 'already_replied'})
            continue
        account = source.get('author', {})
        identity = str(account.get('id') or author(source).lower()) if isinstance(account, dict) else author(source).lower()
        content_hash = hashlib.sha256(str(source.get('content', ''))[:8000].encode()).hexdigest()
        if identity != agent_key or content_hash != state['processed_comments'][key]['content_sha256']:
            report['skipped'].append({'draft_key': key, 'reason': 'source_changed'})
            continue
        if any('WITHDRAW' in fields(str(c.get('content', ''))) and author(c).lower() == participant['name'].lower()
               for c in comments if not c.get('is_deleted')):
            draft['status'] = 'cancelled_withdrawal'
            participant['participation'] = 'withdrawn'
            report['skipped'].append({'draft_key': key, 'reason': 'fresh_withdrawal'})
            continue
        report['candidates'].append({'draft_key': key, 'post_id': pid, 'parent_id': cid, 'content': draft['content']})
        if not execute:
            break
        attempt = {'status': 'attempting', 'post_id': pid, 'parent_id': cid, 'agent_key': agent_key,
                   'attempted_at': now.isoformat(), 'recovery_run_id': os.environ.get('GITHUB_RUN_ID')}
        attempts[key] = attempt
        persist(state)  # Durable checkpoint before any external write.
        result = api('POST', '/posts/' + pid + '/comments', {'parent_id': cid, 'content': draft['content']})
        report['moltbook_writes'] += 1
        item = result.get('comment') or {}
        if not result.get('success') or not item.get('id'):
            report['action'] = 'uncertain_submission_blocked'
            return state, report
        attempt['comment_id'] = str(item['id'])
        verification = item.get('verification') or result.get('verification') or {}
        pending = item.get('verification_status', item.get('verificationStatus')) == 'pending' or bool(verification.get('verification_code'))
        attempt['status'] = 'verification_pending' if pending else 'verified'
        register(state, pid, attempt['comment_id'], 'pending' if pending else 'confirmed', 'authorized_dispatcher')
        if pending:
            recovery = {'draft_key': key, 'comment_id': attempt['comment_id'],
                        'verification_code': verification.get('verification_code'),
                        'challenge_text': verification.get('challenge_text')}
            if checkpoint:
                checkpoint(recovery)
            persist(state)
            if not recovery['verification_code'] or not recovery['challenge_text']:
                report['action'] = 'verification_details_missing'
                return state, report
            state, resumed = dispatch(state, policy, api, persist, True, recovery, checkpoint, now)
            resumed['moltbook_writes'] += report['moltbook_writes']
            return state, resumed
        draft['status'] = 'sent_verified'
        persist(state)
        report.update(action='reply_sent_verified', publishing_enabled=True, comment_id=attempt['comment_id'])
        return state, report
    if execute:
        persist(state)
        report['action'] = 'verification_recovery_required' if report['pending_verifications'] else 'no_eligible_reply'
    return state, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', default='coordination-state.json')
    parser.add_argument('--policy', default='config/reply-policy.json')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--recovery')
    parser.add_argument('--report', default='reply-dispatch-preview.json')
    args = parser.parse_args()
    state = json.loads(pathlib.Path(args.state).read_text())
    policy = json.loads(pathlib.Path(args.policy).read_text())
    recovery = json.loads(pathlib.Path(args.recovery).read_text()) if args.recovery else None
    def persist(updated):
        pathlib.Path(args.state).write_text(json.dumps(updated, indent=2) + '\n')
        if args.execute:
            subprocess.run(['git', 'add', args.state], check=True)
            if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode:
                subprocess.run(['git', 'commit', '-m', 'Save authorized reply dispatcher state'], check=True)
                subprocess.run(['git', 'pull', '--rebase', 'origin', os.environ.get('GITHUB_REF_NAME', 'main')], check=True)
                subprocess.run(['git', 'push', 'origin', 'HEAD:' + os.environ.get('GITHUB_REF_NAME', 'main')], check=True)
    def checkpoint(value):
        pathlib.Path('reply-verification-recovery.json').write_text(json.dumps(value) + '\n')
    try:
        state, report = dispatch(state, policy, MoltbookAPI(os.environ.get('MOLTBOOK_API_KEY', ''), args.execute),
                                 persist, args.execute, recovery, checkpoint)
    except Exception as error:
        pathlib.Path(args.report).write_text(json.dumps({'action': 'failed_without_automatic_repost',
            'error_type': type(error).__name__, 'gemini_calls': 0}) + '\n')
        raise SystemExit(1)
    pathlib.Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'action': report['action'], 'moltbook_writes': report['moltbook_writes'], 'gemini_calls': 0}))


if __name__ == '__main__':
    main()
