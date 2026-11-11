import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'gascity/lib/terminal.py'
spec = importlib.util.spec_from_file_location('terminal_panel', path)
terminal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(terminal)


def decision(id='one', **fields):
    return dict(id=id, question='A choice?', context='Context', options=[{'label': 'First'},
        {'label': 'Second'}], pick=None, delivered=False, closed=False, **fields)


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.view = terminal.View()
        self.view.update({'decisions': [decision()], 'work': []})

    def test_numbered_and_discuss_actions_target_the_current_decision(self):
        self.assertEqual(self.view.handle('2'), ('answer', 'one', 1, ''))
        self.assertEqual(self.view.handle('d'), ('answer', 'one', -2, ''))

    def test_polling_and_new_queue_entries_preserve_custom_draft(self):
        self.view.handle('e')
        for char in 'My 2nd answer': self.view.handle(char)
        self.view.update({'decisions': [decision(), decision('two')], 'work': []})
        self.assertTrue(self.view.editing)
        self.assertEqual(self.view.draft, 'My 2nd answer')
        self.assertEqual(self.view.handle('\n'), ('answer', 'one', -1, 'My 2nd answer'))

    def test_saved_answer_is_retried_without_accepting_a_different_choice(self):
        d = decision()
        d.update(pick=-1, answer='Saved')
        self.view.update({'decisions': [d], 'work': []})
        self.assertIsNone(self.view.handle('1'))
        self.assertEqual(self.view.handle('r'), ('answer', 'one', -1, 'Saved'))

    def test_later_does_not_answer_and_removed_current_stops_editing(self):
        self.view.update({'decisions': [decision(), decision('two')], 'work': []})
        self.assertIsNone(self.view.handle('l'))
        self.assertEqual(self.view.current['id'], 'two')
        self.view.handle('e')
        d = decision('two')
        d.update(pick=0, delivered=True, closed=True)
        self.view.update({'decisions': [decision(), d], 'work': []})
        self.assertFalse(self.view.editing)
        self.assertEqual(self.view.current['id'], 'one')

    def test_render_wraps_and_never_emits_terminal_control_sequences(self):
        d = decision()
        d['question'] = '\x1b[2J' + 'Long title ' * 20
        self.view.update({'decisions': [d], 'work': [{'key':'test', 'title':'Work',
            'status':'waiting', 'note':'Waiting for you', 'group':'Today'}]})
        lines = self.view.lines(24)
        self.assertTrue(all(len(line) <= 24 for line in lines))
        self.assertNotIn('\x1b', '\n'.join(lines))
        self.assertIn('Waiting for you', '\n'.join(lines))

    def test_sending_prevents_duplicate_submission_and_quitting(self):
        self.view.sending = True
        self.assertIsNone(self.view.handle('1'))
        self.assertIsNone(self.view.handle('q'))
        self.view.sending = False
        self.assertEqual(self.view.handle('q'), ('quit',))


if __name__ == '__main__':
    unittest.main()
