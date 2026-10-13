"""Publish the one approved recruitment draft, or verify its recorded post."""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.request

from moltbook_coordinator import register

BASE = 'https://www.moltbook.com/api/v1'
APPROVED_SHA256 = 'ef8a935f305bbc68ff9472e1b88adcaa90480cf0dde6dddd2b23cf27f2c10b11'


def api(method, path, data=None):
    key = os.environ.get('MOLTBOOK_API_KEY')
    if not key:
        raise RuntimeError('Missing existing Moltbook key')
    if (method, path) not in {('POST', '/posts'), ('POST', '/verify')} and not (
            method == 'GET' and re.fullmatch(r'/posts/[A-Za-z0-9-]+', path)):
        raise ValueError('Unsupported publication operation')
    request = urllib.request.Request(BASE + path, method=method,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
        data=json.dumps(data).encode() if data is not None else None)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=50) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError('Moltbook HTTP ' + str(error.code)) from error


def commit_memory(message):
    paths = ['recruitment-publication.json', 'coordination-state.json']
    subprocess.run(['git', 'add', *paths], check=True)
    if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode == 0:
        return
    subprocess.run(['git', 'commit', '-m', message], check=True)
    subprocess.run(['git', 'pull', '--rebase', 'origin', 'main'], check=True)
    subprocess.run(['git', 'push', 'origin', 'HEAD:main'], check=True)


def save(publication, state, message):
    pathlib.Path('recruitment-publication.json').write_text(json.dumps(publication, indent=2) + '\n')
    pathlib.Path('coordination-state.json').write_text(json.dumps(state, indent=2) + '\n')
    commit_memory(message)


def perform(operation, publication, state, draft, request=api, persist=save,
            recovery=None, answer=None):
    if hashlib.sha256(draft).hexdigest() != APPROVED_SHA256:
        raise ValueError('Draft differs from the exact user-approved version')
    if publication.get('approved_sha256') != APPROVED_SHA256:
        raise ValueError('Publication approval hash is missing')
    header, content = draft.decode().split('\n\n', 1)
    title = header.removeprefix('# ')
    report = {'operation': operation, 'gemini_calls': 0,
              'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if operation == 'publish':
        if publication.get('status') != 'approved':
            return {'operation': operation, 'action': 'skipped_existing_attempt',
                    'post_id': publication.get('post_id')}, None
        # A durable marker must reach GitHub before the irreversible external request.
        publication['status'] = 'attempting'
        persist(publication, state, 'Record approved recruitment posting attempt')
        response = request('POST', '/posts', {'submolt_name': 'general', 'title': title,
                                             'content': content.strip()})
        post = response.get('post') or {}
        post_id = post.get('id')
        if not response.get('success') or not post_id:
            raise RuntimeError('Post outcome uncertain; automatic retry blocked')
        publication['post_id'] = str(post_id)
        verification = post.get('verification') or response.get('verification') or {}
        status = post.get('verification_status', post.get('verificationStatus', ''))
        pending = status == 'pending' or bool(verification.get('verification_code')) or bool(response.get('verification_required'))
        publication['status'] = 'verification_pending' if pending else 'verified'
        register(state, str(post_id), verification='pending' if pending else 'confirmed',
                 source='approved_recruitment_post')
        persist(publication, state, 'Record recruitment post and coordination thread')
        report.update(action=publication['status'], post_id=str(post_id), title=title)
        if pending:
            challenge = verification.get('challenge_text')
            code = verification.get('verification_code')
            if not challenge or not code:
                raise RuntimeError('Verification details missing; no guessing or reposting')
            recovery = {'post_id': str(post_id), 'verification_code': code,
                        'challenge_text': challenge, 'approved_sha256': APPROVED_SHA256}
            report['challenge_text'] = challenge  # Never log the verification code or API key.
        return report, recovery
    if operation != 'verify':
        raise ValueError('Unknown operation')
    if publication.get('status') == 'verified':
        return {'operation': operation, 'action': 'already_verified', 'post_id': publication.get('post_id')}, None
    if publication.get('status') != 'verification_pending' or not recovery:
        raise ValueError('No matching pending publication')
    if recovery.get('post_id') != publication.get('post_id') or recovery.get('approved_sha256') != APPROVED_SHA256:
        raise ValueError('Recovery does not match the approved post')
    if not answer or not re.fullmatch(r'-?\d{1,10}\.\d{2}', answer):
        raise ValueError('Verification requires an explicitly calculated decimal answer')
    response = request('POST', '/verify', {'verification_code': recovery['verification_code'], 'answer': answer})
    if response.get('success') is not True:
        raise RuntimeError('Moltbook did not confirm verification')
    publication['status'] = 'verified'
    register(state, publication['post_id'], verification='confirmed', source='approved_recruitment_post')
    persist(publication, state, 'Record verified recruitment post')
    report.update(action='verified', post_id=publication['post_id'], verification_answer=answer)
    return report, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operation', choices=['publish', 'verify'], required=True)
    parser.add_argument('--recovery')
    parser.add_argument('--answer')
    args = parser.parse_args()
    publication = json.loads(pathlib.Path('recruitment-publication.json').read_text())
    state = json.loads(pathlib.Path('coordination-state.json').read_text())
    recovery = json.loads(pathlib.Path(args.recovery).read_text()) if args.recovery else None
    def recorded_request(method, path, data=None):
        response = api(method, path, data)
        if path == '/posts':
            post = response.get('post') or {}
            verification = post.get('verification') or response.get('verification') or {}
            if post.get('id'):
                checkpoint = {'post_id': str(post['id']), 'approved_sha256': APPROVED_SHA256,
                              'verification_code': verification.get('verification_code'),
                              'challenge_text': verification.get('challenge_text')}
                # Retain recovery before any subsequent memory-commit or parsing failure.
                pathlib.Path('recruitment-recovery.json').write_text(json.dumps(checkpoint) + '\n')
                pathlib.Path('recruitment-result.json').write_text(json.dumps({
                    'action': 'post_returned', 'post_id': str(post['id']),
                    'challenge_text': verification.get('challenge_text'), 'gemini_calls': 0}) + '\n')
        return response
    try:
        report, recovery = perform(args.operation, publication, state,
            pathlib.Path('drafts/moltbook-recruitment.md').read_bytes(), request=recorded_request,
            recovery=recovery, answer=args.answer)
        pathlib.Path('recruitment-result.json').write_text(json.dumps(report, indent=2) + '\n')
        if recovery:
            pathlib.Path('recruitment-recovery.json').write_text(json.dumps(recovery) + '\n')
        print(json.dumps(report))
    except Exception as error:
        # An uncertain POST remains durably blocked, with no automatic second submission.
        print('Recruitment operation failed:', str(error))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
