"""Structural public inputs for the five remaining M6 controller panels.

Controller records remain complete. No recursive word or key blacklist is used
to rewrite observations, source prose, prediction content or model answers.
"""
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.retrieval_panel_drivers import public_retrieval_context
from research_loop.ontology import ContractError


def _fields(row, names):
    return {key: row[key] for key in names if key in row}


def _execution(row):
    return {'status': row['status'], 'record': _fields(row['record'], ('stdout', 'stderr', 'exit_code', 'status'))}


def _plan(row):
    return _fields(row, ('question', 'branches', 'budget_units'))


def _origin(row):
    public = _fields(row, ('kind', 'identity', 'task_digest', 'objective', 'claim', 'expected_observation'))
    if 'plan' in row: public['plan'] = _plan(row['plan'])
    if 'plan_trace' in row: public['plan'] = _plan(row['plan_trace']['data']['plan'])
    if 'execution' in row: public['execution'] = _execution(row['execution'])
    return public


def _catalog_item(row):
    kind = row['kind']
    if kind == 'boundary': return _fields(row, ('kind', 'objective'))
    if 'claim' in row: return _fields(row, ('kind', 'claim'))
    if 'plan' in row: return {'kind': kind, 'plan': _plan(row['plan']), 'updates': row.get('updates', [])}
    if kind == 'untested': return {'kind': kind, 'plan': _plan(row['trace']['data']['plan']), 'updates': []}
    if kind == 'anomaly':
        content = row['observation']['payload']['content']
        return {'kind': kind, 'execution': _execution(content['execution']),
                'expected_observation': content['expected_observation'], 'anomaly_confirmed': row['anomaly_confirmed']}
    if kind == 'failed_check':
        trace = row['trace']
        if trace['stage'] == 'execution_result':
            return {'kind': kind, 'execution': _execution(trace['data']['receipt'])}
        # These are actual failed operations, with their literal failure reasons.
        return {'kind': kind, 'failure': _fields(trace['data'], ('reason', 'error', 'error_type', 'failure_reason'))}
    raise ContractError('unsupported public frontier origin')


class M6PublicInputBoundary:
    def __init__(self, coverage, variant):
        if coverage not in {'Q8.1', 'Q8.4', 'Q8.5', 'Q8.6', 'Q8.7'}:
            raise ContractError('public M6 boundary has a closed scope')
        self.coverage, self.variant = coverage, variant
        self.frontier_refs = {}

    def project_evidence_context(self, context):
        """Preserve observed anomalies without repeating controller receipts.

        evidence_only deliberately includes unadmitted roots in RunSession.
        Keep that scientific uncertainty and the actual output in this scope.
        """
        row = context.data()
        if 'records' in row:
            public = []
            for root in row['records']:
                content = root['payload']['content']
                if set(content) != {'execution', 'expected_observation', 'qualification'}:
                    raise ContractError('M6 public evidence requires its declared execution observation')
                public.append({'identity': root['identity'], 'root_id': root['root_id'],
                    'subject_bindings': root['subject_bindings'], 'scientific_admission': root['admitted'],
                    'execution': _execution(content['execution']), 'expected_observation': content['expected_observation']})
            row['records'] = public
        return FrozenRecord.from_dict(row)

    def _frontier_result(self, row):
        result = _fields(row, ('empty_reason', 'programme_complete', 'authority', 'benchmark_admission',
                              'queue_admission', 'semantic_novelty_and_discriminability'))
        reverse = {original: alias for alias, original in self.frontier_refs.items()}
        result['proposals'] = []
        for proposal in row['proposals']:
            public = _fields(proposal, ('kind', 'question', 'observable', 'opposing_predictions'))
            if proposal['origin_ref'] not in reverse: raise ContractError('frontier proposal has no public origin binding')
            public['origin_ref'] = reverse[proposal['origin_ref']]
            result['proposals'].append(public)
        return result

    def project(self, slot, context):
        row = context.data()
        if slot == 'final':
            key = 'retrieval_stage_result' if self.coverage in {'Q8.1', 'Q8.4'} else 'retrieval_final_result'
            detail = row[key]
            public = _fields(detail, ('scientific_verified', 'plan_digest', 'execution_digest', 'execution_status',
                                      'units', 'scientific_independence', 'scientific_evidence_admitted', 'registered_successors'))
            if 'retrieval' in detail: public['retrieval'] = public_retrieval_context(detail['retrieval'])
            if 'review_result' in detail:
                public['review_result'] = _fields(detail['review_result'], ('status', 'correctness'))
            if 'review' in detail: public['review'] = detail['review']
            if 'research_version' in detail:
                version = detail['research_version']; child = version['child']
                public['research_version'] = {**_fields(version, ('state', 'objective_digest')),
                    'child': _fields(child, ('new_objective', 'state')) if child else None}
            if 'frontier' in detail: public['frontier'] = self._frontier_result(detail['frontier'])
            row[key] = public
        elif slot == 'research': row['retrieval'] = public_retrieval_context(row['retrieval'])
        elif slot == 'review':
            row['retrieval'] = public_retrieval_context(row['retrieval'])
            row['typed_request'] = _fields(row['typed_request'], ('operation', 'source_id', 'proposed_objective')) if row['typed_request'] else None
            row.pop('goal_lock', None)
        elif slot in {'review_a', 'review_b'}:
            row = _fields(row, ('role', 'question'))
        elif slot in {'retro_blind', 'retro_reveal'}:
            row = _fields(row, ('history_summary', 'sealed_first_review'))
        elif slot == 'distinguish':
            row = _fields(row, ('execution_digest', 'execution_status', 'scientific_verified'))
        elif slot in {'frontier_review_a', 'frontier_review_b'}:
            if 'origin' in row:
                row = {**_fields(row, ('role', 'question', 'first_review')), 'origin': _origin(row['origin'])}
            else: row = _origin(row)
        elif slot == 'frontier':
            catalog = row['frontier_catalog']
            self.frontier_refs = {f'origin-{index}': original for index, original in enumerate(catalog)}
            row['frontier_catalog'] = {alias: _catalog_item(catalog[original]) for alias, original in self.frontier_refs.items()}
            row.pop('catalog_digest', None)
            if 'review_context' in row: row['review_context'] = {'responses': row['review_context']['responses']}
        return FrozenRecord.from_dict(row)

    def restore_frontier_response(self, response):
        body = response.data()
        if not isinstance(body.get('proposals'), list): return response
        for proposal in body['proposals']:
            if not isinstance(proposal, dict) or proposal.get('origin_ref') not in self.frontier_refs:
                raise ContractError('frontier response cites an unknown public origin')
            proposal['origin_ref'] = self.frontier_refs[proposal['origin_ref']]
        return FrozenRecord.from_dict(body)
