"""Inspect saved AX evidence only; performs no desktop operations."""
import re


def inspect_snapshot(data, expected_prompt=None, expected_model='GPT-5.6 Sol', expected_response=None):
    nodes = []

    def walk(node):
        nodes.append(node)
        for child in node.get('children', []):
            walk(child)

    for window in data.get('windows', []):
        walk(window)
    complete = (data.get('ok') is True and not data.get('truncated', True)
                and not data.get('incomplete', False)
                and data.get('unreadable_elements', 0) == 0
                and all(node.get('role') for node in nodes) and bool(nodes))
    composers = [n for n in nodes if n.get('role') == 'AXTextArea'
                 and n.get('title') == 'Do anything']
    sends = [n for n in nodes if n.get('role') == 'AXButton'
             and n.get('title') == 'Send']
    menu = [n.get('title') for n in nodes if n.get('role') == 'AXMenuItem']
    model_labels = [n.get('title', '') for n in nodes
                    if n.get('role') == 'AXPopUpButton'
                    and n.get('title', '').startswith(expected_model + ' ')]
    menu_evidence = [n.get('value', '') for n in nodes
                     if n.get('role') == 'AXStaticText'
                     and re.match(re.escape(expected_model) + r' .*?, \d+ of \d+\.',
                                  n.get('value', ''))]
    draft_matches = (complete and len(composers) == 1 and expected_prompt is not None
                     and composers[0].get('value') == expected_prompt)
    static_text = [n.get('value', '') for n in nodes if n.get('role') == 'AXStaticText']
    markers = [value for value in static_text if value.startswith('Response complete: ')]
    response_evidence = (complete and expected_response is not None
                         and static_text.count(expected_response) == 1
                         and markers.count('Response complete: ' + expected_response) == 1
                         and expected_prompt is not None and static_text.count(expected_prompt) == 1
                         and len(composers) == 1 and not draft_matches)
    return {
        'complete': complete, 'composer_count': len(composers),
        'draft_matches': draft_matches,
        'send_count': len(sends),
        'send_enabled': len(sends) == 1 and sends[0].get('enabled') is True,
        'send_advertises_press': len(sends) == 1 and 'AXPress' in sends[0].get('actions', []),
        'menu_items': menu, 'closed_picker_model_labels': model_labels,
        'open_menu_model_evidence': menu_evidence,
        'model_verified_with_closed_picker': complete and len(model_labels) == 1,
        'completion_marker_count': len(markers),
        'expected_response_evidence': response_evidence,
        'request_to_chat_binding_verified': False,
        'live_submission_verified': False,
    }
