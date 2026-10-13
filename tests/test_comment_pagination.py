"""Exercise the actual embedded workflow functions without credentials or network."""
import ast
import io
import json
import os
import pathlib
import tempfile
import unittest
import urllib.parse
from unittest.mock import patch

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / '.github/workflows/Moltbook-join-discussion.yml'


def workflow_source():
    text = WORKFLOW.read_text()
    embedded = text.split("          python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
    return '\n'.join(line[10:] for line in embedded.splitlines())


def comment(cid, **extra):
    return {'id': cid, **extra}


class PaginationTests(unittest.TestCase):
    def scan(self, pages):
        calls = []

        def api(method, path):
            self.assertEqual(method, 'GET')
            calls.append(urllib.parse.parse_qs(urllib.parse.urlsplit(path).query))
            return pages[len(calls) - 1]

        functions = [n for n in ast.parse(workflow_source()).body
                     if isinstance(n, ast.FunctionDef) and n.name in
                     {'extract_comments', 'flatten', 'get_thread_comments', 'parent_id'}]
        namespace = {'api': api, 'urllib': __import__('urllib')}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(WORKFLOW), 'exec'), namespace)
        flat, diagnostics = namespace['get_thread_comments']('post')
        for query in calls:
            self.assertEqual(query['sort'], ['old'])
            self.assertEqual(query['limit'], ['100'])
            self.assertNotIn('offset', query)
        return flat, diagnostics, calls

    def test_short_terminal_page_is_complete(self):
        flat, diag, calls = self.scan([{'comments': [comment('root')], 'has_more': False}])
        self.assertTrue(diag['complete'])
        self.assertEqual(len(calls), 1)

    def test_opaque_cursor_and_nested_replies_on_later_page(self):
        token = 'opaque+/=&? cursor'
        pages = [
            {'comments': [comment('first')], 'has_more': True, 'next_cursor': token},
            {'comments': [comment('tracked', replies=[comment('reply', parent_id='tracked',
                          replies=[comment('child', parent_id='reply')])])], 'has_more': False},
        ]
        flat, diag, calls = self.scan(pages)
        self.assertEqual(calls[1]['cursor'], [token])
        self.assertTrue(diag['complete'])
        self.assertEqual([c['id'] for c in flat], ['first', 'tracked', 'reply', 'child'])
        self.assertEqual([c['id'] for c in flat if c.get('parent_id') == 'tracked'], ['reply'])

    def test_empty_terminal_page(self):
        _, diag, _ = self.scan([{'comments': [], 'has_more': False}])
        self.assertTrue(diag['complete'])

    def test_incomplete_metadata(self):
        for metadata, reason in [({}, 'invalid_pagination_metadata'),
                                 ({'has_more': 'false'}, 'invalid_pagination_metadata'),
                                 ({'has_more': True}, 'missing_next_cursor'),
                                 ({'has_more': True, 'next_cursor': ''}, 'missing_next_cursor')]:
            with self.subTest(metadata=metadata):
                _, diag, _ = self.scan([{'comments': [comment('one')], **metadata}])
                self.assertFalse(diag['complete'])
                self.assertEqual(diag['incomplete_reason'], reason)

    def test_repeated_cursor(self):
        _, diag, _ = self.scan([
            {'comments': [comment('one')], 'has_more': True, 'next_cursor': 'same'},
            {'comments': [comment('two')], 'has_more': True, 'next_cursor': 'same'},
        ])
        self.assertEqual(diag['incomplete_reason'], 'pagination_cursor_repeated')

    def test_server_ignores_cursor(self):
        page = {'comments': [comment('one')], 'has_more': True, 'next_cursor': 'next'}
        _, diag, _ = self.scan([page, page])
        self.assertEqual(diag['incomplete_reason'], 'pagination_did_not_advance')

    def test_overlap_deduplicated(self):
        flat, diag, _ = self.scan([
            {'comments': [comment('one')], 'has_more': True, 'next_cursor': 'next'},
            {'comments': [comment('one'), comment('two'), comment('two')], 'has_more': False},
        ])
        self.assertTrue(diag['complete'])
        self.assertEqual([c['id'] for c in flat], ['one', 'two'])

    def test_empty_page_cannot_claim_more(self):
        _, diag, _ = self.scan([{'comments': [], 'has_more': True, 'next_cursor': 'next'}])
        self.assertEqual(diag['incomplete_reason'], 'empty_page_with_more_results')

    def test_malformed_comments(self):
        for payload in [{'has_more': False}, {'comments': None, 'has_more': False},
                        {'success': False, 'comments': [], 'has_more': False}]:
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                self.scan([payload])
        _, diag, _ = self.scan([{'comments': [{'content': 'missing id'}], 'has_more': False}])
        self.assertEqual(diag['incomplete_reason'], 'invalid_comment_items')

    def test_page_limit(self):
        _, diag, calls = self.scan([{'comments': [comment(str(i))], 'has_more': True,
                                    'next_cursor': str(i)} for i in range(20)])
        self.assertFalse(diag['complete'])
        self.assertEqual(diag['incomplete_reason'], 'page_limit_reached')
        self.assertEqual(len(calls), 20)

    def run_detection(self, payloads, publish='false'):
        calls = []
        def get(req, **kwargs):
            self.assertEqual(req.get_method(), 'GET')
            self.assertTrue(req.full_url.startswith('https://www.moltbook.com/api/v1/posts/'))
            calls.append(req.full_url)
            return io.BytesIO(json.dumps(payloads[len(calls) - 1]).encode())
        with tempfile.TemporaryDirectory() as directory:
            destination = pathlib.Path(directory) / 'report.json'
            with patch.dict(os.environ, {'MOLTBOOK_API_KEY': '', 'GEMINI_API_KEY': '',
                                         'MODE': 'check_replies', 'PUBLISH': publish,
                                         'DETECTION_ONLY': 'true'}), \
                 patch('urllib.request.urlopen', side_effect=get), \
                 patch('pathlib.Path', return_value=destination), \
                 patch('builtins.print'):
                try:
                    exec(compile(workflow_source(), str(WORKFLOW), 'exec'), {})
                except SystemExit as error:
                    self.assertEqual(error.code, 1)
            return json.loads(destination.read_text()), calls

    def test_detection_only_finds_reply_without_gemini_or_post(self):
        payloads = [
            {'comments': [comment('804f1d85-5156-4d0a-b2ec-e023513a7323',
                author={'name': 'AutonomousMillion'}, replies=[comment('reply',
                author={'name': 'OtherAgent'}, content='A reply')])], 'has_more': False},
            {'comments': [comment('60aeb6ba-f170-4804-8b65-d48de729af4e')], 'has_more': False},
        ]
        report, calls = self.run_detection(payloads)
        self.assertEqual(report['action'], 'replies_detected')
        self.assertEqual(report['eligible_reply_count'], 1)
        self.assertEqual(report['checked_threads'][0]['replies_found'], 1)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('draft_comment', report)

    def test_detection_only_rejects_publishing_before_network(self):
        report, calls = self.run_detection([], publish='true')
        self.assertIn('publish=false', report['error'])
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
