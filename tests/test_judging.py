import copy
import unittest
from desktop_harness.judging import check_response, validate_judgment, validate_policy

POLICY = {'schema_version':1, 'criteria':{'C4':'Provide a service slot within 08:30–08:45.'},
          'checks':[{'id':'slot', 'kind':'time_window', 'criterion':'C4', 'label':'Ordinary-ticket slot', 'window_start':'08:30','window_end':'08:45'}]}
RESPONSE = 'Ordinary-ticket slot: 08:40–08:45\nT-C first, then T-A.'


class JudgingTest(unittest.TestCase):
    def row(self):
        return {'criterion':'C4','status':'pass','requirement':POLICY['criteria']['C4'],
                'evidence_quote':'Ordinary-ticket slot: 08:40–08:45','reason':'Within the allowed interval.',
                'basis':'deterministic_check','check_id':'slot'}

    def test_real_boundary_interval_passes_and_outside_interval_fails(self):
        self.assertEqual(check_response(POLICY, RESPONSE)[0]['status'], 'pass')
        self.assertEqual(check_response(POLICY, RESPONSE)[0]['end_offset_minutes'], 15)
        for interval in ['08:30–08:35','08:30–08:45']:
            self.assertEqual(check_response(POLICY, 'Ordinary-ticket slot: '+interval)[0]['status'],'pass')
        for interval in ['08:40–08:46','08:29–08:35','08:45–08:40','08:40–08:40']:
            self.assertEqual(check_response(POLICY, 'Ordinary-ticket slot: '+interval)[0]['status'],'fail')

    def test_missing_ambiguous_invalid_or_unattributed_is_unknown(self):
        for response in [None,'No named slot.',RESPONSE+'\n'+RESPONSE,'Ordinary-ticket slot: 25:00–26:00']:
            self.assertEqual(check_response(POLICY,response)[0]['status'],'unknown')

    def test_passing_check_cannot_justify_qwens_timing_downgrade(self):
        row = {**self.row(),'status':'partial','reason':'Starts late, outside the first 15 minutes.'}
        with self.assertRaisesRegex(ValueError,'cannot justify a downgrade'):
            validate_judgment(POLICY, RESPONSE,'partial',4,[row],[],['Late slot'])

    def test_quote_requirement_verdict_and_suggestion_separation(self):
        validate_judgment(POLICY,RESPONSE,'pass',5,[self.row()],['Could try earlier service.'],[])
        for change in [{'requirement':'Slot must start at 08:30.'},{'evidence_quote':'Invented quote'},{'basis':'unsupported'}]:
            with self.assertRaises(ValueError): validate_judgment(POLICY,RESPONSE,'pass',5,[{**self.row(),**change}],[],[])
        with self.assertRaises(ValueError): validate_judgment(POLICY,RESPONSE,'partial',4,[self.row()],[],[])
        with self.assertRaises(ValueError): validate_judgment(POLICY,RESPONSE,'pass',4,[self.row()],[],[])
        with self.assertRaises(ValueError): validate_judgment(POLICY,RESPONSE,'pass',5,[self.row()],[],['Preference'])

    def test_time_failure_and_qualitative_missing_requirements_can_downgrade(self):
        response=RESPONSE.replace('08:45','08:46')
        row={**self.row(),'status':'partial','evidence_quote':'Ordinary-ticket slot: 08:40–08:46'}
        validate_judgment(POLICY,response,'partial',4,[row],[],['Ends beyond the window.'])
        row={**self.row(),'status':'partial','basis':'qualitative','reason':'A different required qualitative element is missing.'}
        validate_judgment(POLICY,RESPONSE,'partial',4,[row],[],['Other requirement missing.'])

    def test_unsupported_policy_and_bad_time_rejected(self):
        for key, value in [('kind','shell'),('window_start','25:00'),('window_end','08:00')]:
            policy=copy.deepcopy(POLICY);policy['checks'][0][key]=value
            with self.assertRaises(ValueError):validate_policy(policy)
        validate_policy(POLICY)

    def test_real_rejected_review_reports_all_actionable_errors(self):
        import json
        from pathlib import Path
        fixture = json.loads((Path(__file__).parent / 'fixtures/rejected-review.json').read_text())
        args = fixture['arguments']
        with self.assertRaises(ValueError) as rejected:
            validate_judgment(fixture['policy'], fixture['response'], args['verdict'], args['score'], args['criteria'], args.get('suggestions'), args['weaknesses'])
        message = str(rejected.exception)
        self.assertIn('Missing field requirement. Use requirement, not exact_requirement', message)
        self.assertIn('(C7)', message)
        self.assertIn('do not use ellipses', message)
        self.assertIn('weaknesses=[]', message)
        fixed = copy.deepcopy(args)
        for row in fixed['criteria']:
            row['requirement'] = row.pop('exact_requirement')
            # Use one real excerpt. Never normalize or accept fabricated quotes.
            if row['evidence_quote'] not in fixture['response']:
                row['evidence_quote'] = fixture['response'].splitlines()[0]
        fixed['suggestions'] = fixed['weaknesses']; fixed['weaknesses'] = []
        validate_judgment(fixture['policy'], fixture['response'], fixed['verdict'], fixed['score'], fixed['criteria'], fixed['suggestions'], fixed['weaknesses'])

    def test_typed_mcp_row_exposes_and_enforces_field_names(self):
        from pydantic import ValidationError
        from desktop_harness.judging import CriterionJudgment, judgment_rows
        schema = CriterionJudgment.model_json_schema()
        for key in ('criterion', 'status', 'requirement', 'evidence_quote', 'reason', 'basis'):
            self.assertIn(key, schema['required'])
        self.assertFalse(schema['additionalProperties'])
        wrong = self.row(); wrong['exact_requirement'] = wrong.pop('requirement')
        with self.assertRaises(ValidationError) as rejected: CriterionJudgment(**wrong)
        self.assertIn('requirement', str(rejected.exception))
        self.assertEqual(judgment_rows([CriterionJudgment(**self.row())]), [self.row()])

    def test_fixed_prompt_suffix_policy_validation(self):
        for invalid in ('', '   ', 3, [], 'x'*32001):
            with self.assertRaises(ValueError): validate_policy({**POLICY, 'fixed_prompt_suffix': invalid})
        validate_policy({**POLICY, 'fixed_prompt_suffix': 'Fixed customer message.'})

    def test_evidence_rendering_equivalence_preserves_source_and_rejects_edits(self):
        from desktop_harness.judging import resolve_evidence_quote
        response = 'You’re right—we sent the wrong color.\nPlease send your order number.'
        self.assertEqual(resolve_evidence_quote(response, "You're right—we sent the wrong color."), response.splitlines()[0])
        self.assertEqual(resolve_evidence_quote(response, "You're right—we sent the wrong color. Please send your order number."), response)
        for invalid in ('You’re wrong—we sent the wrong color.', 'You’re right ... Please send your order number.', 'We issued your label.'):
            self.assertIsNone(resolve_evidence_quote(response, invalid))
        self.assertIsNone(resolve_evidence_quote('You’re right.\nYou’re right.', "You're right."))
