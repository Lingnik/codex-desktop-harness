import copy
import unittest

from desktop_harness.response_reader import inspect_response, response_markers

REQUEST = '272cfc92-691d-45c3-acfa-8966e5b81266'
BEGIN, END = response_markers(REQUEST)
PROMPT = 'Original instruction mentioning ' + BEGIN + ' and ' + END


def node(role='AXGroup', value='', title='', children=None):
    return dict(role=role, value=value, title=title, children=children or [])


def text(value):
    return node('AXStaticText', value=value)


def snapshot(response=None, completion=True, model='GPT-5.6 Sol Medium'):
    composer = node(children=[node('AXTextArea', value='Do anything\n', title='Do anything'),
                              node('AXPopUpButton', title=model)])
    leaves = [text(PROMPT)]
    if completion:
        leaves.append(text('Response complete: summarized response'))
    leaves.extend(text(v) for v in (response if response is not None else [BEGIN, 'Hello.', END]))
    chat = node(children=leaves + [composer])
    return dict(ok=True, truncated=False, incomplete=False, unreadable_elements=0,
                windows=[node('AXWindow', children=[text('repo'), chat])])


def read(data):
    return inspect_response(data, REQUEST, PROMPT, '/tmp/repo', 'GPT-5.6 Sol')


class ResponseReaderTest(unittest.TestCase):
    def test_unsupported_code_control_cannot_be_silently_omitted(self):
        data = snapshot()
        data['windows'][0]['children'][1]['children'].insert(3, node('AXTextArea', value='code()', title='code'))
        self.assertEqual(read(data)['reason'], 'unsupported_response_text_control')
        self.assertIsNone(read(data)['response_text'])

    def test_split_paragraphs_code_and_prompt_markers(self):
        result = read(snapshot([BEGIN, 'First paragraph.', '', 'Second paragraph.',
                                'def answer():', '    return 42', END]))
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['response_text'],
                         'First paragraph.\n\nSecond paragraph.\ndef answer():\n    return 42')
        self.assertEqual(result['completion_marker_text'], 'Response complete: summarized response')
        self.assertTrue(result['request_to_chat_binding_verified'])

    def test_markers_split_across_adjacent_leaves(self):
        result = read(snapshot([BEGIN[:15], BEGIN[15:], 'Body', END[:15], END[15:]]))
        self.assertEqual(result['response_text'], 'Body')

    def test_missing_envelope_is_waiting_before_completion(self):
        self.assertEqual(read(snapshot(['partial'], completion=False))['state'], 'waiting')
        self.assertEqual(read(snapshot(['partial']))['state'], 'uncertain')

    def test_duplicate_envelope_is_uncertain(self):
        result = read(snapshot([BEGIN, 'First', END, BEGIN, 'Second', END]))
        self.assertEqual(result['state'], 'uncertain')
        self.assertIsNone(result['response_text'])

    def test_completion_required(self):
        result = read(snapshot(completion=False))
        self.assertEqual(result['state'], 'waiting')
        self.assertIsNone(result['response_text'])

    def test_durable_completion_without_live_announcement(self):
        data = snapshot(completion=False)
        chat = data['windows'][0]['children'][1]
        actions = [node('AXButton', title=t) for t in ('Copy', 'Rate response', 'Fork chat from here')]
        for action in actions:
            action['enabled'] = True
        chat['children'][-1]['children'][0]['enabled'] = True
        chat['children'][-1:-1] = actions
        result = read(data)
        self.assertEqual(result['response_text'], 'Hello.')
        self.assertEqual(result['completion_method'], 'final_response_actions_and_idle_composer')
        # A Stop control must override even a closed envelope and final actions.
        chat['children'].insert(-1, node('AXButton', title='Stop'))
        self.assertEqual(read(data)['reason'], 'turn_still_running')
        chat['children'].pop(-2)
        # Actions from an earlier response cannot complete this one.
        for action in actions:
            chat['children'].remove(action)
        chat['children'][1:1] = actions
        self.assertEqual(read(data)['state'], 'waiting')

    def test_wrong_model_or_project(self):
        self.assertEqual(read(snapshot(model='GPT-6.1 Sol Medium'))['reason'], 'selected_model_unverified')
        data = snapshot()
        data['windows'][0]['children'][0]['value'] = 'another-repo'
        self.assertEqual(read(data)['reason'], 'workspace_label_missing')

    def test_incomplete_or_clipped_snapshot(self):
        for change in ({'truncated': True}, {'incomplete': True}, {'unreadable_elements': 1},
                       {'ok': False}, {'values_truncated': True}):
            with self.subTest(change=change):
                data = snapshot()
                data.update(change)
                self.assertEqual(read(data)['state'], 'uncertain')
        data = snapshot()
        data['windows'][0]['children'][1]['children'][2]['value_truncated'] = True
        self.assertEqual(read(data)['reason'], 'truncated_values')

    def test_legacy_capture_clipping_is_conservative(self):
        data = snapshot([BEGIN, 'a' * 800, END])
        data['note'] = 'Values capped at 800 characters'
        self.assertEqual(read(data)['reason'], 'possibly_truncated_values')

    def test_multiple_matching_chats_are_uncertain(self):
        data = snapshot()
        data['windows'][0]['children'].append(copy.deepcopy(data['windows'][0]['children'][1]))
        self.assertEqual(read(data)['reason'], 'chat_scope_not_unique')

    def test_prompt_and_composer_in_separate_chats_cannot_bind(self):
        data = snapshot()
        chat = data['windows'][0]['children'][1]
        composer = chat['children'].pop()
        data['windows'][0]['children'].append(node(children=[composer, text('different prompt')]))
        self.assertEqual(read(data)['reason'], 'chat_scope_too_broad')

    def test_composer_descendants_do_not_supply_response(self):
        data = snapshot(response=[], completion=False)
        composer = data['windows'][0]['children'][1]['children'][-1]['children'][0]
        composer['children'] = [text(BEGIN), text('draft echo'), text(END),
                                text('Response complete: draft echo')]
        result = read(data)
        self.assertEqual(result['state'], 'waiting')
        self.assertIsNone(result['response_text'])

    def test_reversed_markers_are_uncertain(self):
        self.assertEqual(read(snapshot([END, 'Body', BEGIN]))['reason'], 'response_envelope_out_of_order')

    def test_duplicate_completion_announcements_are_ambiguous(self):
        data = snapshot()
        data['windows'][0]['children'][1]['children'].insert(2, text('Response complete: another'))
        self.assertEqual(read(data)['reason'], 'ambiguous_response_envelope')

    def test_nonempty_composer_prevents_completion(self):
        data = snapshot()
        data['windows'][0]['children'][1]['children'][-1]['children'][0]['value'] = 'another draft'
        self.assertEqual(read(data)['reason'], 'composer_not_cleared')

    def test_saved_prose_rendering_matches_without_accepting_edits(self):
        import json
        from pathlib import Path
        from desktop_harness.response_reader import prompt_matches
        fixture = json.loads((Path(__file__).parent / 'fixtures/rendered-draft.json').read_text())
        self.assertTrue(prompt_matches(fixture['observed'], fixture['expected']))
        for text in [fixture['observed'].replace('40 customers', '400 customers'), fixture['observed'][:-1], fixture['observed'].replace('BEGIN_CODEX_RESPONSE_', 'BAD_CODEX_RESPONSE_')]:
            self.assertFalse(prompt_matches(text, fixture['expected']))
        for original in ['```\n- code\n\n```', 'line\n    code\n\nnext', 'line  \n\nnext', 'line\n\tcode\n\nnext']:
            self.assertTrue(prompt_matches(original, original))
            self.assertFalse(prompt_matches(original.replace('\n\n', '\n'), original))

    def test_rendered_submitted_prompt_and_rendered_unsent_draft(self):
        wire = PROMPT + '\n\n- ticket one\n- ticket two'
        observed = PROMPT + '\n• ticket one\n• ticket two'
        data = snapshot()
        chat = data['windows'][0]['children'][1]
        chat['children'][0]['value'] = observed
        result = inspect_response(data, REQUEST, wire, '/tmp/repo', 'GPT-5.6 Sol')
        self.assertEqual(result['state'], 'completed')
        chat['children'][0]['value'] = observed.replace('ticket one', 'ticket changed')
        self.assertFalse(inspect_response(data, REQUEST, wire, '/tmp/repo', 'GPT-5.6 Sol')['completion_evidence_verified'])
        chat['children'] = [chat['children'][-1]]
        chat['children'][0]['children'][0]['value'] = observed
        self.assertEqual(inspect_response(data, REQUEST, wire, '/tmp/repo', 'GPT-5.6 Sol')['reason'], 'draft_not_submitted')

    def test_saved_split_prompt_response_is_attributed(self):
        import json
        from pathlib import Path
        root = Path(__file__).parent / 'fixtures'
        data = json.loads((root / 'split-prompt-response.json').read_text())
        task = json.loads((root / 'split-prompt-task.json').read_text())
        result = inspect_response(data, task['request_id'], task['prompt'], task['workspace'], task['desktop_model'])
        self.assertEqual(result['state'], 'completed', result)
        self.assertIn('08:40–08:45', result['response_text'])

    def test_split_prompt_rejects_edits_and_duplicate_user_messages(self):
        import json
        from pathlib import Path
        fixtures = Path(__file__).parent / 'fixtures'
        task = json.loads((fixtures / 'split-prompt-task.json').read_text())
        for corruption in ('fact', 'marker', 'duplicate'):
            data = json.loads((fixtures / 'split-prompt-response.json').read_text())
            def alter(node):
                children = node.get('children', [])
                for index, child in enumerate(children[:-1]):
                    if child.get('title') == 'You said:':
                        if corruption == 'duplicate':
                            children.extend(copy.deepcopy(children[:index+2]))
                        else:
                            def edit(n):
                                if 'value' in n:
                                    n['value'] = n['value'].replace('40 customers', '400 customers') if corruption == 'fact' else n['value'].replace('BEGIN_CODEX_RESPONSE_', 'BAD_CODEX_RESPONSE_')
                                for c in n.get('children', []): edit(c)
                            edit(children[index + 1])
                        return
                for child in children: alter(child)
            alter(data['windows'][0])
            result = inspect_response(data, task['request_id'], task['prompt'], task['workspace'], task['desktop_model'])
            self.assertFalse(result['completion_evidence_verified'], corruption)
