import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import re
from unittest.mock import patch

PANEL = Path(__file__).resolve().parents[1] / 'gascity/lib/panel.py'
spec = importlib.util.spec_from_file_location('panel', PANEL)
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)

FAKE_GC = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['PANEL_TEST_DB'])
db = json.loads(p.read_text())
a = sys.argv[1:]
if a[:1] == ['--city']: a = a[2:]
out = ''
if a[:2] == ['bd', 'list']: out = json.dumps(list(db['beads'].values()))
elif a[:2] == ['bd', 'show']: out = json.dumps([db['beads'][a[2]]])
elif a[:2] == ['bd', 'update']:
    db['beads'][a[2]]['metadata'].update(json.loads(a[a.index('--metadata')+1]))
elif a[:2] == ['bd', 'close']: db['beads'][a[2]]['status'] = 'closed'
elif a[:2] == ['mail', 'send']:
    if db.get('fail_mail'): sys.exit('mail temporarily unavailable')
    key = a[a.index('--dedup')+1]
    if not any(m['key'] == key for m in db['mail']): db['mail'].append({'key':key,'args':a})
else: sys.exit('unexpected command: '+str(a))
p.write_text(json.dumps(db))
print(out)
'''


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'db.json'
        self.db.write_text(json.dumps({'beads': {'ga-test': {
            'id': 'ga-test', 'title': '<Choose>', 'description': 'Context',
            'status': 'open', 'labels': ['decision'], 'metadata': {
                'options': [{'label': 'One'}, {'label': 'Two'}], 'reply_to': 'mayor'}
        }}, 'mail': []}))
        exe = self.root / 'gc'
        exe.write_text(FAKE_GC)
        exe.chmod(0o755)
        self.old_db = os.environ.get('PANEL_TEST_DB')
        os.environ['PANEL_TEST_DB'] = str(self.db)
        self.addCleanup(self.restore_env)
        self.store = panel.Store(str(self.root), str(exe))

    def restore_env(self):
        if self.old_db is None: os.environ.pop('PANEL_TEST_DB', None)
        else: os.environ['PANEL_TEST_DB'] = self.old_db

    def read(self):
        return json.loads(self.db.read_text())

    def test_answer_persists_delivers_and_repeat_does_not_send(self):
        self.store.answer('ga-test', 1)
        self.store.answer('ga-test', 1)
        state = self.read()
        self.assertEqual(state['beads']['ga-test']['metadata']['pick'], 1)
        self.assertTrue(state['beads']['ga-test']['metadata']['delivered'])
        self.assertEqual(state['beads']['ga-test']['status'], 'closed')
        self.assertEqual(len(state['mail']), 1)
        self.assertIn('option 2: "Two"', ' '.join(state['mail'][0]['args']))

    def test_failure_keeps_answer_for_retry_without_changing_choice(self):
        state = self.read()
        state['fail_mail'] = True
        self.db.write_text(json.dumps(state))
        with self.assertRaises(panel.PanelError): self.store.answer('ga-test', -1, 'My answer')
        self.assertEqual(self.read()['beads']['ga-test']['metadata']['answer'], 'My answer')
        with self.assertRaises(panel.PanelError): self.store.answer('ga-test', 0)
        state = self.read()
        state['fail_mail'] = False
        self.db.write_text(json.dumps(state))
        self.store.answer('ga-test', -1, 'My answer')
        self.assertIn('My answer', ' '.join(self.read()['mail'][0]['args']))

    def test_discuss_is_not_approval(self):
        self.store.answer('ga-test', -2)
        self.assertIn('do not act on it yet', ' '.join(self.read()['mail'][0]['args']))

    def test_invalid_and_nondecision_answers_do_not_mutate(self):
        before = self.db.read_text()
        for pick, text in [(2, ''), (-3, ''), (True, ''), (-1, '  ')]:
            with self.assertRaises(panel.PanelError): self.store.answer('ga-test', pick, text)
        self.assertEqual(before, self.db.read_text())
        state = self.read()
        state['beads']['ga-test']['labels'] = ['work']
        self.db.write_text(json.dumps(state))
        with self.assertRaises(panel.PanelError): self.store.answer('ga-test', 0)
        self.assertEqual(self.read()['mail'], [])

    def test_snapshot_keeps_pending_delivery_and_hides_withdrawn(self):
        state = self.read()
        state['beads']['ga-test']['metadata'].update(pick=0, delivered=False)
        self.db.write_text(json.dumps(state))
        pending = self.store.snapshot()['decisions']
        self.assertEqual(pending[0]['id'], 'ga-test')
        self.assertFalse(pending[0]['delivered'])
        state['beads']['ga-test']['metadata']['withdrawn'] = True
        self.db.write_text(json.dumps(state))
        self.assertEqual(self.store.snapshot()['decisions'], [])

    def test_http_requires_same_origin_and_token_and_delivers_valid_answer(self):
        with patch('socket.getfqdn', side_effect=OSError('DNS unavailable')):
            server = panel.make_server(self.store)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(url) as r:
            html = r.read().decode()
            self.assertIn("frame-ancestors 'none'", r.headers['Content-Security-Policy'])
        token = re.search('name="decision-token" content="([^"]+)"', html)[1]
        payload = json.dumps({'id': 'ga-test', 'pick': 0}).encode()
        for headers in [{}, {'X-Decision-Token': token, 'Origin': 'https://evil.example'},
                        {'X-Decision-Token': token, 'Host': 'evil.example'}]:
            req = urllib.request.Request(url+'/api/answer', payload, headers)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(req)
            self.assertEqual(error.exception.code, 403)
        self.assertEqual(self.read()['mail'], [])
        req = urllib.request.Request(url+'/api/answer', payload,
                {'X-Decision-Token': token, 'Origin': url, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as r:
            self.assertEqual(json.load(r), {'ok': True})
        self.assertEqual(len(self.read()['mail']), 1)


if __name__ == '__main__':
    unittest.main()
