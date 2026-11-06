"""Deterministic facts for a qualitative judge; no inference or Desktop actions."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class CriterionJudgment(BaseModel):
    """Explicit MCP schema; field names are part of the tool contract."""
    model_config = ConfigDict(extra='forbid')
    criterion: str = Field(description='Configured criterion ID, for example C4.')
    status: Literal['pass', 'partial', 'fail']
    requirement: str = Field(description="Copy this criterion's exact requirement from eval_checks.criteria. The field is requirement, not exact_requirement.")
    evidence_quote: str = Field(description='One literal contiguous substring of the attributed answer. No ellipses, paraphrase, stitched excerpts or added Markdown.')
    reason: str = Field(description='Explain how the quoted evidence satisfies or violates the configured requirement.')
    basis: Literal['qualitative', 'omission', 'deterministic_check']
    check_id: str | None = Field(default=None, description='Required when basis is deterministic_check; copy an ID from eval_checks.checks.')


def judgment_rows(rows):
    return [row.model_dump(exclude_none=True) if isinstance(row, CriterionJudgment) else row for row in rows] if rows is not None else None


def resolve_evidence_quote(response, quote):
    """Resolve only typography/layout equivalence to one original source span."""
    if not isinstance(response, str) or not isinstance(quote, str) or not quote.strip():
        return None
    if quote in response:
        return quote
    def normalize(text):
        chars = []; starts = []; ends = []
        for index, char in enumerate(text):
            char = "'" if char in "‘’" else char
            if char.isspace():
                if chars and chars[-1] == ' ':
                    ends[-1] = index + 1
                    continue
                char = ' '
            chars.append(char); starts.append(index); ends.append(index + 1)
        return ''.join(chars), starts, ends
    source, starts, ends = normalize(response)
    needle = normalize(quote)[0]
    first = source.find(needle)
    if first < 0 or source.find(needle, first + 1) >= 0:
        return None
    return response[starts[first]:ends[first + len(needle) - 1]]


def resolve_judgment_evidence(response, criteria):
    if not isinstance(criteria, list):
        return criteria, []
    rows = []; resolutions = []
    for row in criteria:
        if not isinstance(row, dict):
            rows.append(row); continue
        updated = dict(row); quote = row.get('evidence_quote')
        matched = resolve_evidence_quote(response, quote)
        if matched is not None and matched != quote:
            updated['evidence_quote'] = matched
            resolutions.append({'criterion': row.get('criterion'), 'submitted_quote': quote,
                                'source_quote': matched, 'method': 'apostrophe_whitespace_equivalence'})
        rows.append(updated)
    return rows, resolutions


def clock_minutes(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('Times must be HH:MM in one specified day')
    hour, minute = map(int, value.split(':'))
    return hour * 60 + minute


def validate_policy(policy):
    if not isinstance(policy, dict) or policy.get('schema_version') != 1:
        raise ValueError('Judge policy requires schema_version 1')
    suffix = policy.get('fixed_prompt_suffix')
    if 'fixed_prompt_suffix' in policy and (not isinstance(suffix, str) or not suffix.strip() or len(suffix) > 32000):
        raise ValueError('fixed_prompt_suffix must be nonempty text of at most 32000 characters')
    criteria = policy.get('criteria')
    if not isinstance(criteria, dict) or not criteria or len(criteria) > 30:
        raise ValueError('Judge policy requires 1–30 explicit criteria')
    for key, value in criteria.items():
        if not isinstance(key, str) or not re.fullmatch(r'C\d+', key) or not isinstance(value, str) or not value.strip() or len(value) > 4000:
            raise ValueError('Criteria require C-number IDs and exact nonempty requirements')
    checks = policy.get('checks', [])
    if not isinstance(checks, list) or len(checks) > 30:
        raise ValueError('Checks must be a list with at most 30 entries')
    ids = set()
    for check in checks:
        if not isinstance(check, dict) or check.get('kind') != 'time_window':
            raise ValueError('Only explicit time_window checks are supported')
        name = check.get('id')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', name) or name in ids:
            raise ValueError('Check IDs must be unique')
        ids.add(name)
        if check.get('criterion') not in criteria or not isinstance(check.get('label'), str) or not check['label'].strip() or len(check['label']) > 200:
            raise ValueError('Check requires an existing criterion and exact response label')
        if clock_minutes(check['window_start']) >= clock_minutes(check['window_end']):
            raise ValueError('Time windows must have positive duration within the same day')
    return policy


def check_response(policy, response):
    results = []
    for check in policy.get('checks', []) if policy else []:
        result = {'id': check['id'], 'criterion': check['criterion'], 'kind': 'time_window',
                  'allowed_window': [check['window_start'], check['window_end']],
                  'status': 'unknown', 'note': 'Only the labelled interval is checked; other criterion requirements still need judgment.'}
        if response is None:
            result['reason'] = 'no_attributed_response'
        else:
            pattern = r'(?m)^(?:[•*-] )?' + re.escape(check['label']) + r':[ \t]*(?:\n[ \t]*)?((?:[01]\d|2[0-3]):[0-5]\d)[ \t]*[–-][ \t]*((?:[01]\d|2[0-3]):[0-5]\d)(?![0-9:])'
            matches = list(re.finditer(pattern, response))
            if len(matches) != 1:
                result['reason'] = 'labelled_interval_missing_or_ambiguous'
            else:
                match = matches[0]; start, end = map(clock_minutes, match.groups())
                lower, upper = clock_minutes(check['window_start']), clock_minutes(check['window_end'])
                valid = lower <= start < end <= upper
                result.update(status='pass' if valid else 'fail', evidence_quote=match.group(0),
                              observed_window=list(match.groups()), start_offset_minutes=start-lower,
                              end_offset_minutes=end-lower, reason='contained_in_allowed_window' if valid else 'outside_window_or_nonpositive_duration')
        results.append(result)
    return results


def validate_judgment(policy, response, verdict, score, criteria, suggestions, weaknesses):
    if not policy:
        if criteria is not None:
            raise ValueError('Configure an explicit judge policy before structured criterion judgments')
        return
    if not isinstance(criteria, list) or len(criteria) != len(policy['criteria']):
        raise ValueError('Supply one structured judgment for every configured criterion; use eval_checks for exact requirements')
    by_check = {c['id']: c for c in check_response(policy, response)}
    seen = set(); statuses = []; errors = []
    for index, row in enumerate(criteria):
        key = row.get('criterion') if isinstance(row, dict) else None
        if key not in policy['criteria'] or key in seen:
            errors.append(f'criteria[{index}]: Each configured criterion must occur exactly once')
            continue
        seen.add(key)
        prefix = f'criteria[{index}] ({key})'
        status = row.get('status'); statuses.append(status)
        if status not in ('pass', 'partial', 'fail'):
            errors.append(prefix + ': Criterion status must be pass, partial or fail')
        if 'requirement' not in row:
            errors.append(prefix + ': Missing field requirement. Use requirement, not exact_requirement; copy eval_checks.criteria[' + key + '] verbatim')
        elif row['requirement'] != policy['criteria'][key]:
            errors.append(prefix + ': Copy the exact configured requirement; do not introduce a preference as a criterion. Expected: ' + policy['criteria'][key])
        quote = row.get('evidence_quote')
        if not isinstance(quote, str) or not quote.strip() or not isinstance(response, str) or quote not in response:
            errors.append(prefix + ': Criterion evidence_quote must be a literal nonempty substring of the attributed response. Copy one contiguous excerpt; do not use ellipses or join excerpts')
        if not isinstance(row.get('reason'), str) or not row['reason'].strip() or len(row['reason']) > 4000:
            errors.append(prefix + ': Criterion judgment needs a reason tied to its requirement')
        basis = row.get('basis')
        if basis not in ('qualitative', 'omission', 'deterministic_check'):
            errors.append(prefix + ': Basis must be qualitative, omission or deterministic_check')
        if basis == 'deterministic_check':
            check = by_check.get(row.get('check_id'))
            if not check or check['criterion'] != key:
                errors.append(prefix + ': Cite a deterministic check for this criterion')
            elif check['status'] == 'unknown' or (status == 'pass' and check['status'] == 'fail'):
                errors.append(prefix + ': Unknown or failing checks cannot justify a passing deterministic judgment')
            elif status != 'pass' and check['status'] != 'fail':
                errors.append(prefix + ': A passing or unknown deterministic check cannot justify a downgrade')
    expected = 'fail' if 'fail' in statuses else 'partial' if 'partial' in statuses else 'pass'
    if verdict != expected:
        errors.append('Overall verdict must agree with the criterion judgments')
    if verdict == 'pass' and (weaknesses or (score is not None and score != 5)):
        errors.append('All criteria passed: score must be 5 or null; put beyond-rubric preferences in suggestions and set weaknesses=[]')
    if errors:
        raise ValueError('Review validation failed; no assessment or review was saved. Fix all listed fields in one correction: ' + '; '.join(errors))
