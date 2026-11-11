#!/usr/bin/env python3
"""Keyboard Decisions panel for a terminal or tmux split. No model required."""
import argparse
import curses
import importlib.util
import os
from pathlib import Path
import queue
import sys
import textwrap
import threading
import time
from typing import NamedTuple

# Load the adjacent module explicitly so the pack's isolated Python launcher works.
spec = importlib.util.spec_from_file_location('decision_panel_store', Path(__file__).with_name('panel.py'))
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)


def plain(value):
    return ''.join(c for c in str(value) if c.isprintable() or c == '\n')


class Row(NamedTuple):
    text: str
    style: str = 'text'
    key: str = ''


class View:
    def __init__(self):
        self.state = {'decisions': [], 'work': []}
        self.later = []
        self.drafts = {}
        self.editing = False
        self.scroll = 0
        self.error = ''
        self.notice = 'Connecting to Gas City...'
        self.sending = False
        self.show_done = False

    @property
    def pending(self):
        ds = [d for d in self.state['decisions'] if not d['delivered'] or not d['closed']]
        return sorted(ds, key=lambda d: self.later.index(d['id']) if d['id'] in self.later else -1)

    @property
    def current(self):
        return self.pending[0] if self.pending else None

    @property
    def draft(self):
        return self.drafts.get(self.current['id'], '') if self.current else ''

    def update(self, state):
        before = self.current
        self.state = state
        after = self.current
        if not before or not after or before['id'] != after['id'] or after['pick'] is not None:
            self.editing = False
            self.scroll = 0

    def click(self, key):
        return self.handle(key, pointer=True)

    def handle(self, key, pointer=False):
        if self.sending:
            return None
        if pointer:
            key = {'send': '\n', 'cancel': '\x1b'}.get(key, key)
        d = self.current
        if self.editing and d and (not pointer or key in ('\n', '\x1b')):
            if key in ('\n', '\r', curses.KEY_ENTER):
                if self.draft.strip():
                    return ('answer', d['id'], -1, self.draft.strip())
            elif key == '\x1b':
                self.editing = False
            elif key in ('\x7f', '\b', curses.KEY_BACKSPACE):
                self.drafts[d['id']] = self.draft[:-1]
            elif isinstance(key, str) and key.isprintable() and len(self.draft) < 10000:
                self.drafts[d['id']] = self.draft + key
            return None
        if key == 'q':
            return ('quit',)
        if key in (curses.KEY_DOWN, 'j'):
            self.scroll += 1
        elif key in (curses.KEY_UP, 'k'):
            self.scroll = max(0, self.scroll - 1)
        elif key == curses.KEY_NPAGE:
            self.scroll += 10
        elif key == curses.KEY_PPAGE:
            self.scroll = max(0, self.scroll - 10)
        elif key == 'w':
            self.show_done = not self.show_done
        elif key == 'r':
            if d and d['pick'] is not None:
                return ('answer', d['id'], d['pick'], d.get('answer') or '')
            return ('refresh',)
        elif d and d['pick'] is None:
            if isinstance(key, str) and key in '123456789' and len(key) == 1:
                pick = int(key) - 1
                if pick < len(d['options']):
                    return ('answer', d['id'], pick, '')
            elif key == 'd':
                return ('answer', d['id'], -2, '')
            elif key == 'e':
                self.editing = True
            elif key == 'l' and len(self.pending) > 1:
                self.later = [id for id in self.later if id != d['id']] + [d['id']]
                self.editing = False
                self.scroll = 0
        return None

    def lines(self, width):
        return [row.text for row in self.rows(width)]

    def rows(self, width):
        width = max(1, width)
        out = []

        def add(value='', style='text', key=''):
            for line in plain(value).split('\n'):
                out.extend(Row(part, style, key) for part in
                           (textwrap.wrap(line, width, replace_whitespace=True) or ['']))

        d = self.current
        add(f'DECISIONS  |  {len(self.pending)} waiting', 'heading')
        add('-' * min(width, 48), 'muted')
        if d:
            add(d['id'] + (f"  from {d['sender']}" if d.get('sender') else ''), 'muted')
            add(d['question'])
            add()
            if d.get('context'):
                add(d['context'], 'muted')
                add()
            if d['pick'] is not None:
                pick = d['pick']
                label = ('Discuss first' if pick == -2 else d.get('answer', '') if pick == -1
                         else d['options'][pick]['label'])
                add('Saved: ' + label, 'waiting')
                add('[r] Finish delivery / close decision', 'option', 'r')
            else:
                for i, option in enumerate(d['options']):
                    rec = ' (recommended)' if i == d.get('recommended') else ''
                    style = 'recommended' if rec else 'option'
                    add(f"[{i+1}] {option['label']}{rec}", style, str(i+1))
                    if option.get('detail'):
                        add('    ' + option['detail'], style, str(i+1))
                    add()
                add('[e] Own answer', 'option', 'e')
                add('[d] Discuss first', 'option', 'd')
                if len(self.pending) > 1:
                    add('[l] Later', 'option', 'l')
        else:
            add('All caught up. New decisions appear here.', 'done')
        add()
        items = self.state['work']
        counted = [w for w in items if w['status'] != 'dropped']
        done = sum(w['status'] == 'done' for w in counted)
        add(f'WORK  |  {done}/{len(counted)} done', 'heading')
        add('-' * min(width, 48), 'muted')
        if not items:
            add('No work on the list yet.')
        groups = {}
        for w in items:
            if not self.show_done and w['status'] in ('done', 'dropped'):
                continue
            groups.setdefault(w.get('group') or 'Today', []).append(w)
        order = {'running': 0, 'review': 1, 'waiting': 2, 'blocked': 3, 'todo': 4, 'done': 5, 'dropped': 6}
        for name, work in groups.items():
            add(name, 'heading')
            for w in sorted(work, key=lambda w: (w.get('order') if w.get('order') is not None else 1e9,
                                                order.get(w['status'], 9))):
                add(f"[{w['status']}] {w['key']}  {w['title']}", w['status'])
                if w.get('note'):
                    add('  ' + w['note'], 'muted')
                add()
        add('[w] ' + ('Hide' if self.show_done else 'Show') + ' finished work', 'option', 'w')
        return out


def colors():
    styles = {'heading': curses.A_BOLD, 'recommended': curses.A_BOLD,
              'option': curses.A_BOLD, 'muted': curses.A_DIM, 'toolbar': curses.A_REVERSE}
    if not curses.has_colors():
        return styles
    try:
        curses.start_color()
        background = curses.COLOR_BLACK
        try:
            curses.use_default_colors()
            background = -1
        except curses.error:
            pass
        roles = {'heading': curses.COLOR_CYAN, 'recommended': curses.COLOR_GREEN,
                 'option': curses.COLOR_CYAN, 'running': curses.COLOR_CYAN,
                 'review': curses.COLOR_MAGENTA, 'waiting': curses.COLOR_YELLOW,
                 'blocked': curses.COLOR_RED, 'done': curses.COLOR_GREEN,
                 'error': curses.COLOR_RED, 'input': curses.COLOR_YELLOW}
        for pair, (role, foreground) in enumerate(roles.items(), 1):
            if pair >= curses.COLOR_PAIRS:
                break
            curses.init_pair(pair, foreground, background)
            styles[role] = curses.color_pair(pair) | curses.A_BOLD
    except curses.error:
        pass
    return styles


def run(screen, store):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.timeout(150)
    styles = colors()
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(0)
    except curses.error:
        pass
    view = View()
    requests, results = queue.Queue(), queue.Queue()

    def worker():
        while True:
            action = requests.get()
            try:
                if action[0] == 'answer':
                    store.answer(*action[1:])
                results.put((action[0], store.snapshot(), None))
            except panel.PanelError as e:
                results.put((action[0], None, str(e)))

    threading.Thread(target=worker, daemon=True).start()
    requests.put(('refresh',))
    fetching, next_poll = True, time.monotonic() + 8
    while True:
        try:
            kind, state, error = results.get_nowait()
            if kind == 'answer':
                view.sending = False
            fetching = view.sending
            view.error = error or ''
            if state is not None:
                view.update(state)
                view.notice = ('Answer delivered. ' if kind == 'answer' else '') + time.strftime('Updated %H:%M:%S')
            elif kind == 'answer':
                view.editing = False
                # Refresh saved-answer state even when delivery failed.
                requests.put(('refresh',))
                fetching = True
            next_poll = time.monotonic() + 8
        except queue.Empty:
            pass
        if not fetching and time.monotonic() >= next_poll:
            requests.put(('refresh',))
            fetching = True
        height, width = screen.getmaxyx()
        screen.erase()
        targets = []

        def draw(y, text, attr=0):
            if y < 0 or y >= height or width < 2:
                return
            try:
                screen.addnstr(y, 0, plain(text), width - 1, attr)
            except curses.error:
                pass

        def buttons(y, items):
            x = 0
            for label, key in items:
                text = f'[{label}] '
                if x >= width - 1:
                    break
                end = min(width - 1, x + len(text) - 1)
                try:
                    screen.addnstr(y, x, text, width - 1 - x, styles.get('toolbar', 0))
                except curses.error:
                    pass
                targets.append((y, x, end, key))
                x += len(text)

        if height < 8 or width < 20:
            draw(0, 'Enlarge pane (20x8 min). q quits')
        else:
            body = view.rows(width - 1)
            visible = height - 4
            view.scroll = min(view.scroll, max(0, len(body) - visible))
            for y, row in enumerate(body[view.scroll:view.scroll + visible]):
                draw(y, row.text, styles.get(row.style, 0))
                if row.key:
                    targets.append((y, 0, width - 1, row.key))
            draw(height - 4, '-' * (width - 1), styles.get('muted', 0))
            draw(height - 3, view.error or ('Sending answer...' if view.sending else view.notice),
                 styles.get('error', 0) if view.error else styles.get('muted', 0))
            if view.editing:
                draw(height - 2, 'Answer > ' + view.draft[-max(1, width - 12):] + '_', styles.get('input', 0))
                targets.append((height - 2, 0, width - 1, 'e'))
                buttons(height - 1, [('Send', 'send'), ('Cancel', 'cancel')])
            else:
                buttons(height - 2, [('e Write', 'e'), ('d Discuss', 'd'), ('l Later', 'l')])
                buttons(height - 1, [('Up', 'k'), ('Down', 'j'), ('r Refresh', 'r'), ('w Done', 'w'), ('q Quit', 'q')])
        screen.refresh()
        try:
            key = screen.get_wch()
        except curses.error:
            continue
        if key == curses.KEY_MOUSE:
            try:
                _, x, y, _, flags = curses.getmouse()
            except curses.error:
                continue
            if flags & curses.BUTTON4_PRESSED:
                view.scroll = max(0, view.scroll - 3)
                continue
            if flags & getattr(curses, 'BUTTON5_PRESSED', 0):
                view.scroll += 3
                continue
            if not flags & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                continue
            target = next((key for row, start, end, key in targets if row == y and start <= x < end), None)
            action = view.click(target) if target else None
        else:
            action = view.handle(key)
        if not action:
            continue
        if action[0] == 'quit':
            return
        if action[0] == 'answer':
            view.sending = True
            view.error = ''
            requests.put(action)
            fetching = True
        elif not fetching:
            requests.put(action)
            fetching = True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--city', default=os.environ.get('GC_CITY_PATH') or os.environ.get('GC_CITY'))
    args = p.parse_args()
    root = Path(args.city).resolve() if args.city else Path.cwd().resolve()
    if not args.city:
        root = next((d for d in (root, *root.parents) if (d / 'city.toml').is_file()), root)
    if not (root / 'city.toml').is_file():
        p.error('Run inside a Gas City or pass --city /path/to/city')
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        p.error('An interactive terminal is required (run in a tmux pane)')
    try:
        curses.wrapper(run, panel.Store(root))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
