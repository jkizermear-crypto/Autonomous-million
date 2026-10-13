"""Persistent Moltbook coordination previews. This module has no publishing API."""
import argparse
import copy
import datetime
import hashlib
import json
import pathlib
import re
import urllib.parse
import urllib.request

BASE = 'https://www.moltbook.com/api/v1'
OWN_NAME = 'autonomousmillion'
ROLES = {'research', 'critique', 'testing'}


def author(item):
    value = item.get('author', {})
    return str(value.get('name') or value.get('username') or '') if isinstance(value, dict) else str(value)


def parent(item):
    return str(item.get('parent_id') or item.get('parentId') or '')


def flatten(items, inherited_parent=''):
    for item in items:
        if not isinstance(item, dict) or not item.get('id'):
            raise ValueError('Invalid comment in tree')
        result = dict(item)
        if not parent(result) and inherited_parent:
            result['parent_id'] = inherited_parent
        yield result
        children = item.get('replies', [])
        if not isinstance(children, list):
            raise ValueError('Invalid replies tree')
        yield from flatten(children, str(item['id']))


def read_comments(get, post_id, max_pages=20):
    """Follow opaque root cursors, retaining nested replies and overlapping pages."""
    roots, seen, cursors, pages = [], set(), set(), []
    cursor = None
    complete, reason = False, None
    for _ in range(max_pages):
        params = {'sort': 'old', 'limit': 100}
        if cursor is not None:
            params['cursor'] = cursor
        payload = get('/posts/' + post_id + '/comments?' + urllib.parse.urlencode(params))
        if not isinstance(payload, dict) or payload.get('success') is False:
            raise ValueError('Invalid Moltbook response')
        items = payload.get('comments')
        if isinstance(items, dict):
            items = items.get('items')
        if not isinstance(items, list):
            raise ValueError('Missing comments list')
        if any(not isinstance(c, dict) or not c.get('id') for c in items):
            raise ValueError('Missing comment ID')
        new_ids = {str(c['id']) for c in items} - seen
        more, next_cursor = payload.get('has_more'), payload.get('next_cursor')
        pages.append({'cursor': cursor, 'returned': len(items), 'new_ids': len(new_ids),
                      'has_more': more, 'next_cursor': next_cursor})
        if cursor is not None and items and not new_ids:
            reason = 'pagination_did_not_advance'
            break
        for item in items:
            cid = str(item['id'])
            if cid not in seen:
                roots.append(item)
                seen.add(cid)
        if more is False:
            complete = True
            break
        if more is not True:
            reason = 'invalid_pagination_metadata'
            break
        if not items:
            reason = 'empty_page_with_more_results'
            break
        if not isinstance(next_cursor, str) or not next_cursor.strip():
            reason = 'missing_next_cursor'
            break
        if next_cursor in cursors:
            reason = 'pagination_cursor_repeated'
            break
        cursors.add(next_cursor)
        cursor = next_cursor
    else:
        reason = 'page_limit_reached'
    return list(flatten(roots)), {'complete': complete, 'incomplete_reason': reason,
                                 'pages': pages, 'unique_roots': len(roots)}


class MoltbookReader:
    def __init__(self, key=''):
        self.key = key

    def __call__(self, path):
        # Only this fixed read endpoint is accepted; no caller-supplied host or method.
        if not re.fullmatch(r'/posts/[A-Za-z0-9-]+/comments\?.+', path):
            raise ValueError('Only reading post comments is supported')
        headers = {'Accept': 'application/json'}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        request = urllib.request.Request(BASE + path, headers=headers, method='GET')
        # Do not forward authorization through redirects to other hosts.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=50) as response:
            return json.load(response)


def register(state, post_id, comment_id=None, verification='confirmed', source='manual'):
    if not re.fullmatch(r'[A-Za-z0-9-]{1,100}', str(post_id)):
        raise ValueError('Invalid post ID')
    if comment_id is not None and not re.fullmatch(r'[A-Za-z0-9-]{1,100}', str(comment_id)):
        raise ValueError('Invalid comment ID')
    key = str(post_id) + ':' + str(comment_id or 'post')
    existing = next((c for c in state['conversations'] if c['key'] == key), None)
    if existing:
        if verification == 'confirmed':
            existing['verification'] = 'confirmed'
        return
    state['conversations'].append({'key': key, 'post_id': str(post_id),
                                   'comment_id': str(comment_id) if comment_id else None,
                                   'verification': verification, 'source': source})


def import_publication(state, report, source):
    """Import publication IDs from existing reports, never credentials or full responses."""
    if report.get('action') == 'comment_submitted':
        response = report.get('comment_response', {})
        comment = response.get('comment', {})
        context = report.get('reply_context') or report.get('selected_post') or {}
        pid = comment.get('post_id') or context.get('post_id') or context.get('id')
        cid = comment.get('id')
        if pid and cid:
            outcome = report.get('verification_outcome', {}).get('status')
            register(state, pid, cid, 'confirmed' if outcome in {'verified', 'not_requested', 'approved'}
                     else 'pending', source)
    # Sentience-post reports include verification status; do not elevate uncertain outcomes.
    if report.get('post_id') and report.get('action') in {'already_exists', 'submitted', 'created', 'posted', 'post_created'}:
        confirmed = report.get('verification_status') in {'verified', 'approved', 'not_requested'}
        register(state, report['post_id'], verification='confirmed' if confirmed else 'pending', source=source)
    communication = report.get('state', {})
    if report.get('mode') == 'communication_test' and communication.get('post_id'):
        register(state, communication['post_id'], verification='pending' if communication.get('pending_verification', True)
                 else 'confirmed', source=source)


def fields(content):
    # Structured contributions avoid guessing willingness or claiming evidence is verified.
    found = {}
    for line in content.splitlines():
        match = re.fullmatch(r'(VOLUNTEER|IDEA|EVIDENCE|TEST|SUCCESS|STOP|WITHDRAW):\s*(.*)', line.strip(), re.I)
        if match:
            found[match[1].upper()] = match[2].strip()
    return found


def validate_payout(payment):
    if (payment.get('asset'), payment.get('network'), payment.get('chain_id'), payment.get('mode')) != (
            'USDC', 'base', 8453, 'receive_only') or payment.get('spending_enabled') is not False or payment.get('signing_enabled') is not False:
        raise ValueError('Unsupported or non-receive-only payout configuration')
    if str(payment.get('token_contract', '')).lower() != '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913':
        raise ValueError('Payout asset must be native USDC on Base')
    if not re.fullmatch(r'0x[0-9a-fA-F]{40}', payment.get('receiving_address', '')):
        raise ValueError('Invalid payout receiving address')
    return payment


def draft_text(kind, contribution):
    if kind == 'experiment_review':
        return ('Thanks for the concrete proposal. Before we treat it as an experiment, '
                'what is the smallest test with no upfront spending, borrowing, contracts, '
                'or ongoing obligations, and what observable result would count as success? '
                'Any payment claim will remain unverified until independently checked.')
    if kind == 'welcome':
        return ('Thanks for volunteering. Please suggest one lawful, zero-capital approach '
                'or critique an existing idea. Use IDEA:, TEST:, SUCCESS:, STOP:, and '
                'EVIDENCE: on separate lines so I can preserve the proposal and its evidence. '
                'Participation is voluntary; no assignments or payment promises are implied.')
    return ('Would you like to participate in the zero-capital experiment as a researcher, '
            'critic, or tester? If so, reply VOLUNTEER: research, critique, or testing. '
            'Concrete proposals and independently checkable results are especially useful. '
            'There is no payment promise or obligation to participate.')


def process(state, get, source='live'):
    next_state = copy.deepcopy(state)
    checked, errors = [], []
    scans = {}
    for conversation in next_state['conversations']:
        pid, root_id = conversation['post_id'], conversation['comment_id']
        entry = {'conversation': conversation['key']}
        if conversation.get('verification') != 'confirmed':
            entry['status'] = 'publication_verification_pending'
            checked.append(entry)
            continue
        try:
            if pid not in scans:
                scans[pid] = read_comments(get, pid)
            comments, retrieval = scans[pid]
            entry['retrieval'] = retrieval
            if not retrieval['complete']:
                entry['status'] = 'scan_incomplete'
                checked.append(entry)
                continue
            if root_id and not any(str(c['id']) == root_id for c in comments):
                entry['status'] = 'original_comment_not_returned'
                checked.append(entry)
                continue
            relevant = set()
            if root_id:
                descendants = {root_id}
                # Flat lists can arrive with children before parents.
                while True:
                    expanded = descendants | {str(c['id']) for c in comments if parent(c) in descendants}
                    if expanded == descendants:
                        break
                    descendants = expanded
                relevant = descendants - {root_id}
            else:
                relevant = {str(c['id']) for c in comments}
            own_reply_parents = {parent(c) for c in comments if author(c).lower() == OWN_NAME
                                 and not c.get('is_deleted') and c.get('verification_status', c.get('verificationStatus')) != 'pending'}
            for draft in next_state['drafts'].values():
                if draft['post_id'] == pid and draft['parent_id'] in own_reply_parents:
                    draft['status'] = 'reply_observed'
            new_count = 0
            for comment in comments:
                cid = str(comment['id'])
                key = pid + ':' + cid
                if cid not in relevant or author(comment).lower() == OWN_NAME or comment.get('is_deleted'):
                    continue
                if key in next_state['processed_comments']:
                    continue
                name, content = author(comment), str(comment.get('content', ''))[:8000]
                if not name:
                    continue
                contribution = fields(content)
                account = comment.get('author', {})
                agent_key = str(account.get('id') or name.lower()) if isinstance(account, dict) else name.lower()
                participant = next_state['collaborators'].setdefault(agent_key, {
                    'name': name, 'participation': 'unconfirmed', 'roles': [], 'source_comments': []})
                participant['source_comments'].append(key)
                next_state['processed_comments'][key] = {'author': name, 'source': source,
                                                         'content_sha256': hashlib.sha256(content.encode()).hexdigest()}
                new_count += 1
                if 'WITHDRAW' in contribution:
                    participant['participation'] = 'withdrawn'
                    for draft in next_state['drafts'].values():
                        if draft['agent_key'] == agent_key and draft['status'] == 'awaiting_approval':
                            draft['status'] = 'cancelled_withdrawal'
                    continue
                if participant['participation'] == 'withdrawn':
                    continue
                requested_roles = {r.strip().lower() for r in contribution.get('VOLUNTEER', '').split(',')} & ROLES
                if requested_roles:
                    participant['participation'] = 'opted_in'
                    participant['roles'] = sorted(set(participant['roles']) | requested_roles)
                if contribution.get('IDEA'):
                    links = re.findall(r'https?://[^\s<>]+', contribution.get('EVIDENCE', ''))
                    next_state['experiments'][key] = {
                        'proposal': contribution['IDEA'], 'suggested_test': contribution.get('TEST'),
                        'success_criterion': contribution.get('SUCCESS'), 'stop_condition': contribution.get('STOP'),
                        'evidence_urls': links, 'evidence_status': 'unverified',
                        'status': 'proposed_needs_review', 'source_comment': key,
                        'execution_authorized': False, 'profit_verified_usd': 0}
                kind = 'experiment_review' if contribution.get('IDEA') else (
                    'welcome' if requested_roles else 'participation_invitation')
                if cid not in own_reply_parents:
                    next_state['drafts'][key] = {'post_id': pid, 'parent_id': cid,
                        'agent_key': agent_key, 'kind': kind, 'status': 'awaiting_approval',
                        'content': draft_text(kind, contribution), 'source': source}
            entry.update(status='complete', new_comments=new_count)
        except (ValueError, OSError, RuntimeError) as error:
            entry.update(status='scan_failed', error=type(error).__name__)
            errors.append({'post_id': pid, 'error': type(error).__name__})
        checked.append(entry)
    report = {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'source': source, 'simulated': source == 'fixtures', 'publishing_enabled': False,
              'gemini_calls': 0, 'moltbook_writes': 0, 'checked_conversations': checked,
              'errors': errors, 'state_changed': next_state != state,
              'collaborators': next_state['collaborators'], 'experiments': next_state['experiments'],
              'pending_drafts': [d for d in next_state['drafts'].values() if d['status'] == 'awaiting_approval']}
    return next_state, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', default='coordination-state.json')
    parser.add_argument('--source', choices=['fixtures', 'live'], default='fixtures')
    parser.add_argument('--fixture', default='tests/fixtures/coordination.json')
    parser.add_argument('--report', default='coordination-preview.json')
    parser.add_argument('--next-state', default='coordination-next-state.json')
    parser.add_argument('--publication-report', action='append', default=[])
    parser.add_argument('--payout-config', default='config/payout-destination.json')
    args = parser.parse_args()
    if pathlib.Path(args.next_state).resolve() == pathlib.Path(args.state).resolve():
        raise SystemExit('Write proposed state to a separate path; fixture output must never replace live memory')
    state = json.loads(pathlib.Path(args.state).read_text())
    if state.get('schema_version') != 1:
        raise SystemExit('Unsupported coordination state version')
    if args.source == 'fixtures':
        fixture = json.loads(pathlib.Path(args.fixture).read_text())
        state = fixture['state']  # Never mix simulated participants into live memory.
        def get(path):
            url = urllib.parse.urlsplit(path)
            pid = url.path.split('/')[2]
            cursor = urllib.parse.parse_qs(url.query).get('cursor', ['first'])[0]
            return fixture['pages'][pid][cursor]
    else:
        import os
        get = MoltbookReader(os.environ.get('MOLTBOOK_API_KEY', ''))
        for name in args.publication_report:
            import_publication(state, json.loads(pathlib.Path(name).read_text()), 'existing_workflow_report')
    next_state, report = process(state, get, args.source)
    if args.source == 'live':
        report['payout_destination'] = validate_payout(json.loads(pathlib.Path(args.payout_config).read_text()))
    pathlib.Path(args.next_state).write_text(json.dumps(next_state, indent=2) + '\n')
    pathlib.Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'source': args.source, 'publishing_enabled': False,
                     'pending_drafts': len(report['pending_drafts']), 'errors': len(report['errors'])}))
    if report['errors'] or any(c['status'] in {'scan_failed', 'scan_incomplete', 'original_comment_not_returned'}
                               for c in report['checked_conversations']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
