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

    def test_clicking_an_option_while_editing_chooses_instead_of_typing(self):
        self.view.handle('e')
        self.view.handle('A')
        self.assertEqual(self.view.click('2'), ('answer', 'one', 1, ''))
        self.assertEqual(self.view.draft, 'A')
        self.view.sending = True
        self.assertIsNone(self.view.click('1'))

    def test_clickable_custom_send_cancel_and_work_controls(self):
        self.view.click('e')
        self.view.handle('A')
        self.view.click('w')
        self.assertTrue(self.view.editing)
        self.assertTrue(self.view.show_done)
        self.assertEqual(self.view.click('send'), ('answer', 'one', -1, 'A'))
        self.view.click('cancel')
        self.assertFalse(self.view.editing)
        self.assertEqual(self.view.draft, 'A')

    def test_wrapped_options_keep_click_targets_and_recommended_style(self):
        d = decision()
        d['recommended'] = 1
        d['options'][1] = {'label': 'A longer second option that wraps', 'detail': 'More details'}
        self.view.update({'decisions': [d], 'work': []})
        rows = self.view.rows(18)
        choices = [row for row in rows if row.key == '2']
        self.assertGreater(len(choices), 1)
        self.assertTrue(all(row.style == 'recommended' for row in choices))
        self.assertTrue(all(len(row.text) <= 18 for row in rows))


if __name__ == '__main__':
    unittest.main()
