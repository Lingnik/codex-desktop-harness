"""Conservative request attribution and rendered-text extraction from saved AX trees.

No desktop APIs are used. This bounded reader requires a per-request response
 envelope; it does not reconstruct Markdown from accessibility leaf text.
"""
from pathlib import Path
import re
from uuid import UUID


def response_markers(request_id):
    token = UUID(request_id).hex.upper()
    return f'BEGIN_CODEX_RESPONSE_{token}', f'END_CODEX_RESPONSE_{token}'


def prompt_matches(observed, expected):
    """Exact equality or the single known prose AX rendering; no fuzzy matching."""
    if observed == expected:
        return True
    lines = expected.split('\n')
    if ('`' in expected or '~~~' in expected or '\r' in expected or
            any(line and (line.startswith((' ', '\t')) or line.endswith((' ', '\t'))) for line in lines)):
        return False
    rendered = '\n'.join('• ' + line[2:] if line.startswith('- ') else line
                         for line in lines if line != '')
    return observed == rendered


def split_prompt_matches(values, expected):
    # Keep every character of every leaf/list marker, permitting only AX node
    # seams with zero or one newline. No substring or whitespace stripping.
    lines = expected.split('\n')
    if ('`' in expected or '~~~' in expected or '\r' in expected or
            any(line and (line.startswith((' ', '\t')) or line.endswith((' ', '\t'))) for line in lines)):
        return False
    target = '\n'.join('• ' + line[2:] if line.startswith('- ') else line for line in lines if line != '')
    positions = {0}
    for index, value in enumerate(values):
        if not value:
            return False
        next_positions = set()
        for offset in positions:
            for seam in ('', '\n') if index else ('',):
                piece = seam + value
                if target.startswith(piece, offset):
                    next_positions.add(offset + len(piece))
        positions = next_positions
        if not positions:
            return False
    return len(target) in positions


def submitted_prompt_anchors(nodes, expected):
    anchors = {id(n): n for n in nodes if n.get('role') == 'AXStaticText'
               and not n.get('children') and prompt_matches(n.get('value'), expected)}
    def leaves(node):
        if node.get('role') not in ('AXGroup', 'AXList', 'AXListMarker', 'AXStaticText'):
            return None
        if not node.get('children'):
            return [node] if node.get('role') in ('AXListMarker', 'AXStaticText') else []
        output = []
        for child in node['children']:
            found = leaves(child)
            if found is None:
                return None
            output.extend(found)
        return output
    def bodies(node):
        found = leaves(node)
        if found and split_prompt_matches([n.get('value', '') for n in found], expected):
            anchors[id(found[-1])] = found[-1]
        for child in node.get('children', []):
            bodies(child)
    for node in nodes:
        children = node.get('children', [])
        for index, child in enumerate(children[:-1]):
            if child.get('role') == 'AXHeading' and child.get('title') == 'You said:':
                bodies(children[index + 1])
    return anchors


def inspect_response(data, request_id, wire_prompt, workspace, desktop_model):
    """Return completed, waiting, or uncertain, exposing text only on completion."""
    begin, end = response_markers(request_id)
    result = {'request_id': request_id, 'state': 'uncertain', 'response_text': None,
              'completion_evidence_verified': False,
              'request_to_chat_binding_verified': False,
              'workspace_check': 'visible_project_label_only'}

    def finish(reason, state='uncertain', **evidence):
        return {**result, **evidence, 'state': state, 'reason': reason}

    nodes, parent, descendants = [], {}, {}

    def walk(node, ancestor=None):
        if not isinstance(node, dict):
            raise ValueError('invalid node')
        start = len(nodes)
        nodes.append(node)
        parent[id(node)] = ancestor
        for child in node.get('children', []):
            walk(child, node)
        descendants[id(node)] = (start, len(nodes))

    try:
        for window in data.get('windows', []):
            walk(window)
    except (TypeError, ValueError):
        return finish('malformed_snapshot')
    if (data.get('ok') is not True or data.get('truncated', True)
            or data.get('incomplete', False) or data.get('unreadable_elements', 0)
            or not nodes or any(not node.get('role') for node in nodes)):
        return finish('incomplete_snapshot')
    if (data.get('values_truncated', False)
            or any(node.get('value_truncated', False) for node in nodes)):
        return finish('truncated_values')
    # Earlier probes did not report clipping. An exactly capped value is unsafe.
    cap_match = re.search(r'Values capped at (\d+) characters', data.get('note', ''))
    if cap_match and any('value_truncated' not in node
                         and len(node.get('value', '')) >= int(cap_match[1])
                         for node in nodes):
        return finish('possibly_truncated_values')

    def subtree(node):
        start, stop = descendants[id(node)]
        return nodes[start:stop]

    def composer(node):
        return node.get('role') == 'AXTextArea' and node.get('title') == 'Do anything'

    def leaf_text(node):
        return node.get('role') == 'AXStaticText' and not node.get('children')

    anchors = submitted_prompt_anchors(nodes, wire_prompt)

    def exact_prompt(node):
        return id(node) in anchors

    # A unique narrowest ancestor must contain both the submitted prompt and
    # composer. A sidebar/other chat cannot supply the missing half.
    candidates = []
    for node in nodes:
        children = subtree(node)
        if sum(composer(n) for n in children) == 1 and sum(exact_prompt(n) for n in children) == 1:
            candidates.append(node)
    narrowest = [n for n in candidates if not any(c is not n and any(c is item for item in subtree(n))
                                                for c in candidates)]
    if len(narrowest) != 1:
        drafted = any(composer(n) and prompt_matches(n.get('value'), wire_prompt) for n in nodes)
        return finish('draft_not_submitted' if drafted else 'chat_scope_not_unique',
                      'waiting' if drafted else 'uncertain')
    scope = narrowest[0]
    if scope.get('role') in ('AXWindow', 'AXWebArea'):
        return finish('chat_scope_too_broad')
    scoped = subtree(scope)
    compose = next(n for n in scoped if composer(n))
    prompt = next(n for n in scoped if exact_prompt(n))
    window = scope
    while parent[id(window)] is not None:
        window = parent[id(window)]
    project = Path(workspace).name
    if not project or not any(n.get('title') == project or
                              (leaf_text(n) and n.get('value') == project)
                              for n in subtree(window)):
        return finish('workspace_label_missing')
    # Search outward from the textarea to its nearest model-bearing ancestor,
    # bounded by this chat scope; never use an unrelated model picker.
    owner = compose
    model_labels = []
    while True:
        model_labels = [n.get('title', '') for n in subtree(owner)
                        if n.get('role') == 'AXPopUpButton'
                        and (n.get('title', '').startswith('GPT-')
                             or n.get('title', '').startswith(desktop_model + ' '))]
        if model_labels or owner is scope:
            break
        owner = parent[id(owner)]
    if len(model_labels) != 1 or not model_labels[0].startswith(desktop_model + ' '):
        return finish('selected_model_unverified', observed_model_labels=model_labels)
    result.update(request_to_chat_binding_verified=True,
                  verified_model_label=model_labels[0], chat_scope_path=scope.get('path'))
    excluded = {id(n) for n in subtree(compose)}
    after = scoped[scoped.index(prompt) + 1:]
    if any(n.get('role') in ('AXTextArea', 'AXTextField') and id(n) not in excluded
           and n.get('value') for n in after):
        return finish('unsupported_response_text_control')
    leaves = [n.get('value', '') for n in after if leaf_text(n) and id(n) not in excluded]
    announcements = [v for v in leaves if v.startswith('Response complete: ')]
    response_leaves = [v for v in leaves if not v.startswith('Response complete: ')]
    rendered = '\n'.join(response_leaves)
    # A marker may itself span adjacent AX leaves. Only inserted newlines may
    # intervene; no other whitespace/content is discarded from the response.
    def marker_pattern(marker):
        return re.compile('\n?'.join(re.escape(char) for char in marker))
    starts, ends = list(marker_pattern(begin).finditer(rendered)), list(marker_pattern(end).finditer(rendered))
    evidence = {'begin_marker_count': len(starts), 'end_marker_count': len(ends),
                'completion_marker_count': len(announcements),
                'completion_marker_text': announcements[0] if len(announcements) == 1 else None,
                'response_representation': 'rendered_ax_leaf_text'}
    if len(starts) > 1 or len(ends) > 1 or len(announcements) > 1:
        return finish('ambiguous_response_envelope', **evidence)
    if len(starts) != 1 or len(ends) != 1:
        return finish('response_envelope_missing', 'uncertain' if announcements else 'waiting', **evidence)
    if ends[0].start() < starts[0].end():
        return finish('response_envelope_out_of_order', **evidence)
    # Live-region announcements can disappear before a later observation. A
    # closed envelope followed by the final-answer actions is durable evidence,
    # provided the composer is idle and no running control remains in this chat.
    busy = any(n.get('role') == 'AXProgressIndicator' or
               (n.get('role') == 'AXButton' and n.get('title', '').lower() in
                ('stop', 'stop generating', 'stop response', 'cancel')) for n in scoped)
    if busy:
        return finish('turn_still_running', 'waiting', **evidence)
    offset = 0
    end_node = None
    for n in after:
        if leaf_text(n) and id(n) not in excluded and not n.get('value', '').startswith('Response complete: '):
            offset += len(n.get('value', ''))
            if offset >= ends[0].end():
                end_node = n
                break
            offset += 1  # Separator inserted between accessibility leaves.
    tail = after[after.index(end_node) + 1:] if end_node is not None else []
    actions = [n.get('title') for n in tail if n.get('role') == 'AXButton'
               and n.get('enabled') is True]
    settled_actions = all(actions.count(title) == 1 for title in
                          ('Copy', 'Rate response', 'Fork chat from here'))
    durable = settled_actions and compose.get('enabled') is True
    if not announcements and not durable:
        return finish('completion_not_observed', 'waiting', **evidence)
    evidence['completion_method'] = 'live_announcement' if announcements else 'final_response_actions_and_idle_composer'
    if compose.get('value', '').strip() not in ('', 'Do anything'):
        return finish('composer_not_cleared', **evidence)
    text = rendered[starts[0].end():ends[0].start()].strip('\r\n')
    return finish('response_envelope_completed', 'completed', response_text=text,
                  completion_evidence_verified=True, **evidence)
