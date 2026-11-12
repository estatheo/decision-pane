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

    def test_progress_segments_fill_width_and_exclude_dropped(self):
        items = [{'status': status} for status in ['done', 'done', 'review', 'running',
            'waiting', 'blocked', 'todo', 'dropped']]
        result = terminal.progress(items, 21)
        self.assertEqual((result.done, result.total, result.percent), (2, 7, 29))
        self.assertEqual(result.segments, (('done', '█'*6), ('review', '█'*3),
            ('running', '█'*3), ('waiting', '█'*3), ('blocked', '█'*3), ('todo', '░'*3)))
        self.assertEqual(sum(len(text) for _, text in result.segments), 21)

    def test_empty_and_narrow_progress_keep_their_requested_width(self):
        empty = terminal.progress([], 9)
        self.assertEqual((empty.percent, empty.total), (0, 0))
        self.assertEqual(empty.segments, (('todo', '░'*9),))
        narrow = terminal.progress([{'status': 'done'}, {'status': 'review'}, {'status':'todo'}], 2)
        self.assertEqual(sum(len(text) for _, text in narrow.segments), 2)

    def test_overall_and_group_progress_include_hidden_done_rows(self):
        items = [dict(key=str(i), title='Work', status=status, group='Build')
                 for i, status in enumerate(['done', 'review', 'running', 'dropped'])]
        self.view.update({'decisions': [], 'work': items})
        rows = self.view.rows(26)
        text = '\n'.join(row.text for row in rows)
        self.assertIn('1/3 done', text)
        self.assertIn('33%', text)
        self.assertIn('Build', text)
        self.assertNotIn('[done]', text)
        self.assertEqual(len([row for row in rows if row.spans and '█' in row.text]), 2)
        self.assertTrue(all(len(row.text) <= 26 for row in rows))


if __name__ == '__main__':
    unittest.main()
