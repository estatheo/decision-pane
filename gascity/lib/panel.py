#!/usr/bin/env python3
"""Local Decisions UI for Codex and other Gas City agents. Standard library only."""
import argparse
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import socketserver
import subprocess
import threading
import webbrowser


class PanelError(Exception):
    pass


class Store:
    def __init__(self, city, gc=None):
        self.city = str(Path(city).resolve())
        self.gc = gc or os.environ.get('GC_BIN') or shutil.which('gc') or 'gc'
        self.lock = threading.Lock()

    def run(self, *args):
        try:
            r = subprocess.run([self.gc, '--city', self.city, *args],
                               capture_output=True, text=True, timeout=25)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise PanelError(f'Gas City is unavailable: {e}') from e
        if r.returncode:
            raise PanelError(r.stderr.strip()[-500:] or 'Gas City command failed')
        return r.stdout

    def query(self, *args):
        text = self.run('bd', *args, '--json')
        # Some versions print a routing notice before the JSON document.
        starts = [i for i in (text.find('['), text.find('{')) if i >= 0]
        try:
            return json.loads(text[min(starts):])
        except (ValueError, TypeError) as e:
            raise PanelError('Gas City returned invalid JSON') from e

    def snapshot(self):
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        opened = self.query('list', '--label-any', 'decision,work', '--limit', '0')
        recent = self.query('list', '--label-any', 'decision,work', '--all',
                            '--updated-after', yesterday, '--limit', '0')
        rows = {b['id']: b for b in [*opened, *recent]}
        decisions, work = [], []
        today = dt.date.today().isoformat()
        for b in sorted(rows.values(), key=lambda b: b.get('created_at', '')):
            m = b.get('metadata') or {}
            labels = b.get('labels') or []
            if 'decision' in labels and not m.get('withdrawn'):
                if b.get('status') == 'closed' and m.get('pick') is None:
                    continue
                decisions.append(dict(id=b['id'], question=b.get('title', ''),
                    context=b.get('description', ''), options=m.get('options', []),
                    recommended=m.get('recommended'), sender=m.get('from', ''),
                    pick=m.get('pick'), answer=m.get('answer', ''),
                    delivered=bool(m.get('delivered')), closed=b.get('status') == 'closed'))
            if 'work' in labels and not m.get('removed'):
                status = m.get('status', 'done' if b.get('status') == 'closed' else 'todo')
                day = m.get('day', b.get('created_at', '')[:10])
                if status in ('done', 'dropped') and day != today:
                    continue
                work.append(dict(id=b['id'], key=m.get('key', b['id']),
                    title=b.get('title', ''), status=status, note=m.get('note', ''),
                    group=m.get('group') or 'Today', who=m.get('who', ''),
                    order=m.get('order'), link=m.get('link', '')))
        return dict(city=self.city, decisions=decisions, work=work)

    def answer(self, bead_id, pick, text=''):
        with self.lock:
            result = self.query('show', bead_id)
            b = result[0] if isinstance(result, list) and result else result
            if not isinstance(b, dict) or 'decision' not in b.get('labels', []):
                raise PanelError('This item is not a decision')
            m = b.get('metadata') or {}
            options = m.get('options') or []
            if (type(pick) is not int or pick < -2 or pick >= len(options)
                    or not isinstance(text, str) or len(text) > 10000
                    or (pick == -1 and not text.strip())):
                raise PanelError('Choose a valid option or enter an answer')
            text = text.strip() if pick == -1 else ''
            if m.get('withdrawn'):
                raise PanelError('This decision was withdrawn')
            saved = m.get('pick') is not None
            if saved and (m['pick'] != pick or (m.get('answer') or '') != text):
                raise PanelError('An answer is already saved; retry that answer')
            if b.get('status') == 'closed' and not saved:
                raise PanelError('This decision is already closed')
            if m.get('delivered'):
                if b.get('status') != 'closed':
                    self.run('bd', 'close', bead_id, '--reason', 'answered via local panel')
                return
            recipient = m.get('reply_to') or b.get('created_by')
            if not recipient:
                raise PanelError('No reply recipient. Set reply_to on this decision before answering.')
            if not saved:
                self.run('bd', 'update', bead_id, '--metadata', json.dumps(dict(
                    pick=pick, answer=text, answered_at=dt.datetime.now(dt.timezone.utc).isoformat())))
            if pick == -2:
                answer = 'that they want to discuss it before deciding'
            elif pick == -1:
                answer = f'in their own words: "{text}"'
            else:
                answer = f'option {pick+1}: "{options[pick]["label"]}"'
            subject = f'DECISION {bead_id}: the user answered {answer}.'
            instruction = ('Ask them about it in chat; do not act on it yet.' if pick == -2
                           else 'Act on it now. Do not ask them again.')
            body = f'{subject}\nQuestion: {b.get("title", "")}\nRaised by: {m.get("from", "")}\n{instruction}'
            self.run('mail', 'send', recipient, '-s', subject, '-m', body,
                     '--notify', '--dedup', f'decision-answer:{bead_id}')
            self.run('bd', 'update', bead_id, '--metadata', json.dumps({'delivered': True}))
            self.run('bd', 'close', bead_id, '--reason', 'answered via local panel')


def make_server(store, port=0):
    token = secrets.token_urlsafe(32)

    class LocalServer(ThreadingHTTPServer):
        def server_bind(self):
            # HTTPServer's reverse DNS lookup can stall offline or under a VPN.
            socketserver.TCPServer.server_bind(self)
            self.server_name = 'localhost'
            self.server_port = self.server_address[1]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def allowed_host(self):
            return self.headers.get('Host') in (
                f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def respond(self, status, data, content_type='application/json', nonce=None):
            body = json.dumps(data).encode() if content_type == 'application/json' else data.encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; connect-src 'self'; "
                f"style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed_host():
                return self.respond(403, {'error': 'Invalid host'})
            if self.path == '/':
                nonce = secrets.token_urlsafe(24)
                html = Path(__file__).with_name('panel.html').read_text()
                return self.respond(200, html.replace('__TOKEN__', token).replace('__NONCE__', nonce),
                                    'text/html', nonce)
            if self.path != '/api/state':
                return self.respond(404, {'error': 'Not found'})
            try:
                self.respond(200, store.snapshot())
            except PanelError as e:
                self.respond(503, {'error': str(e)})

        def do_POST(self):
            origin = self.headers.get('Origin')
            allowed_origins = (f'http://127.0.0.1:{self.server.server_port}',
                               f'http://localhost:{self.server.server_port}')
            if (not self.allowed_host() or self.headers.get('X-Decision-Token') != token
                    or (origin is not None and origin not in allowed_origins)):
                return self.respond(403, {'error': 'Invalid panel request'})
            if self.path != '/api/answer':
                return self.respond(404, {'error': 'Not found'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 20000:
                    raise ValueError('Invalid request size')
                a = json.loads(self.rfile.read(size))
                if not isinstance(a, dict) or not isinstance(a.get('id'), str):
                    raise ValueError('Invalid answer')
                store.answer(a['id'], a.get('pick'), a.get('text', ''))
                self.respond(200, {'ok': True})
            except (ValueError, PanelError) as e:
                self.respond(400, {'error': str(e)})

    server = LocalServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--city', default=os.environ.get('GC_CITY_PATH') or os.environ.get('GC_CITY'))
    p.add_argument('--port', type=int, default=0, help='Loopback port (default: choose an available port)')
    p.add_argument('--no-open', action='store_true', help='Print the URL without opening a browser')
    a = p.parse_args()
    if a.port < 0 or a.port > 65535:
        p.error('--port must be between 0 and 65535')
    root = Path(a.city).resolve() if a.city else Path.cwd().resolve()
    if not a.city:
        root = next((d for d in (root, *root.parents) if (d / 'city.toml').is_file()), root)
    if not (root / 'city.toml').is_file():
        p.error('No city.toml found. Run inside a Gas City or pass --city /path/to/city')
    server = make_server(Store(root), a.port)
    url = f'http://127.0.0.1:{server.server_port}/'
    print(f'Decisions panel: {url}\nCity: {root}\nPress Ctrl-C to stop.', flush=True)
    if not a.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
