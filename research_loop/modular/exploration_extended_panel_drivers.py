"""Train-only Q7.3–Q7.6 drivers with distinct causal module operations."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Mapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.exploration_panel_drivers import (
    _diagnostic, _requirements, _verified, _subject, _trusted_execution_material,
)
from research_loop.modular.feasibility_panel_drivers import _map, _hex, _prepare_inputs, _execute, _execution_public, _invoke
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ScientificState
from research_loop.modular.modules.exploration import ExplorationBudget, ExplorationRatioCandidate, InstrumentRepair
from research_loop.modular.modules.review import ReviewEngine
from research_loop.ontology import ContractError

VARIANTS = {'Q7.3': ('zero', 'low', 'medium', 'high'), 'Q7.4': ('invalid_measure', 'repair', 'old_evidence'),
            'Q7.5': ('valid_known', 'novel_refuted', 'infeasible', 'easy_valid'),
            'Q7.6': ('contract_only', 'real_counterexample')}
LIMITS = {'Q7.3': (3, 4, 8), 'Q7.4': (3, 2, 4), 'Q7.5': (3, 1, 2), 'Q7.6': (4, 1, 2)}
FACETS = {'mechanical_status': ('passed', 'failed', 'unknown'), 'semantic_status': ('passed', 'failed', 'unknown'),
          'diagnostic_value': ('effective', 'waste', 'unknown', 'not_applicable'),
          'main_progress': ('completed', 'incomplete', 'unknown', 'not_applicable'),
          'prior_art_status': ('matched', 'not_matched', 'unknown'),
          'old_instrument_status': ('valid', 'invalid', 'unknown')}


def _authority(raw, identity):
    row = dict(_map(raw, 'authority contract'))
    if set(row) != {'contract_id', 'source_id', 'authorities'} or row['source_id'] != identity.group_id:
        raise ContractError('authority source drift')
    required_text(row['contract_id'], 'contract id')
    pair = row['authorities']
    if not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(p, Mapping) or set(p) != {'authority_id', 'source_group'} for p in pair):
        raise ContractError('two observation sources required')
    for p in pair:
        for v in p.values(): required_text(v, 'authority identity')
    if len({p['authority_id'] for p in pair}) != 2 or len({p['source_group'] for p in pair}) != 2 or identity.group_id in {p['source_group'] for p in pair}:
        raise ContractError('independent observation source collision')
    return row


def _material_item(task, experiment, raw):
    row = dict(_map(raw, 'extended exploration material'))
    if set(row) != {'source_id', 'data_version', 'public_issue', 'hard_constraint', 'authority_contract', 'jobs', 'config'}:
        raise ContractError('extended material fields incomplete')
    if row['source_id'] != task.identity.group_id or row['data_version'] != task.identity.dataset_version:
        raise ContractError('extended source or version drift')
    required_text(row['public_issue'], 'public issue')
    if row['hard_constraint'] not in ('none', 'authorization', 'resource'):
        raise ContractError('extended hard constraint invalid')
    row['authority_contract'] = _authority(row['authority_contract'], task.identity)
    if not isinstance(row['jobs'], list) or not row['jobs']:
        raise ContractError('actual public jobs required')
    row['jobs'] = [_diagnostic(job, task) for job in row['jobs']]
    if any(job['requirements'] != {'execution_units': 1, 'token_units': 1} for job in row['jobs']):
        raise ContractError('extended jobs require the same one-unit resource opportunity')
    ids = {job['diagnostic_id'] for job in row['jobs']}
    if len(ids) != len(row['jobs']):
        raise ContractError('job identities duplicate')
    config = dict(_map(row['config'], 'extended configuration'))
    if experiment == 'Q7.3':
        if set(config) != {'ratio_id', 'exploration_percent', 'control_percent', 'main_ids', 'diagnostic_ids'}:
            raise ContractError('ratio configuration invalid')
        for key in ('exploration_percent', 'control_percent'):
            if type(config[key]) is not int or not 0 <= config[key] <= 100:
                raise ContractError('ratio percentages must be integers')
        ExplorationRatioCandidate(config['ratio_id'], task.identity, config['exploration_percent'])
        flat = []
        for key in ('main_ids', 'diagnostic_ids'):
            if not isinstance(config[key], list) or len(config[key]) != 4 or any(not isinstance(v, str) for v in config[key]):
                raise ContractError('four jobs per ratio role are required')
            flat += config[key]
        if set(flat) != ids or len(set(flat)) != 8:
            raise ContractError('ratio roles must partition eight frozen jobs')
    elif experiment == 'Q7.4':
        if set(config) != {'old_id', 'repair_id', 'instrument_id'} or {config['old_id'], config['repair_id']} != ids or len(ids) != 2:
            raise ContractError('instrument repair requires exact old and new jobs')
        required_text(config['instrument_id'], 'instrument id')
    elif experiment == 'Q7.5':
        if set(config) != {'observation_id', 'observation_claim', 'novelty_claim'} or {config['observation_id']} != ids:
            raise ContractError('four-dimension claim configuration invalid')
        for val in config.values(): required_text(val, 'claim binding')
    else:
        if set(config) != {'observation_id', 'theory', 'construct'} or {config['observation_id']} != ids:
            raise ContractError('semantic review configuration invalid')
        for val in config.values(): required_text(val, 'semantic binding')
    row['config'] = config
    return row


def freeze_extended_exploration_bundle(task: PublicTask, *, materials: Mapping, budget: FrozenRecord):
    expected_budget = {key: {'model_calls': n[0], 'execution_opportunities': n[1], 'verification_calls': n[2]} for key, n in LIMITS.items()}
    if not isinstance(task, PublicTask) or not isinstance(budget, FrozenRecord) or budget.data() != expected_budget:
        raise ContractError('caller public task and matched extended budgets required')
    task.identity.require_train()
    if any(type(v) is not int for row in budget.data().values() for v in row.values()):
        raise ContractError('budget counters require literal integers')
    if set(materials) != set(VARIANTS) or any(set(materials[key]) != set(VARIANTS[key]) for key in VARIANTS):
        raise ContractError('all four extended obligations and variants must remain represented')
    clean = {key: {name: _material_item(task, key, item) for name, item in rows.items()} for key, rows in materials.items()}
    ratio_configs = [item['config'] for item in clean['Q7.3'].values()]
    if len({r['ratio_id'] for r in ratio_configs}) != 4 or len({r['exploration_percent'] for r in ratio_configs}) != 4 or len({r['control_percent'] for r in ratio_configs}) != 1:
        raise ContractError('four distinct ratios and one fixed control allocation required')
    menus = []
    for item in clean['Q7.3'].values():
        shared = {k: v for k, v in item.items() if k != 'config'}
        shared['roles'] = {k: item['config'][k] for k in ('main_ids', 'diagnostic_ids')}
        menus.append(FrozenRecord.from_dict(shared).content_hash)
    if len(set(menus)) != 1:
        raise ContractError('ratio comparison must share identical source, jobs and issue')
    return FrozenRecord.from_dict({'schema': 'extended-exploration-panel-bundle-v1', 'identity': task.identity.data(),
        'payload_digest': task.payload.content_hash, 'budget': budget.data(), 'budget_digest': budget.content_hash, 'materials': clean})


def extended_exploration_injection(experiment_id, variant, *, task, evidence):
    public = PublicTask(DataIdentity.parse(task.data()['identity']), FrozenRecord.from_dict(task.data()['payload']))
    body = evidence.data()
    bundle = freeze_extended_exploration_bundle(public, materials=body.get('materials', {}), budget=FrozenRecord.from_dict(body.get('budget', {})))
    if evidence.content_hash != bundle.content_hash or experiment_id not in VARIANTS or variant not in VARIANTS[experiment_id]:
        raise ContractError('extended scenario binding mismatch')
    return {'schema': 'extended-exploration-controller-v1', 'bundle': bundle.data()}


def _bound(workflow, cell, scenario):
    row = scenario.data()
    if set(row) != {'experiment_id', 'variant', 'controller_input', 'base', 'controls'} or row['experiment_id'] != cell.coverage_id or row['variant'] != cell.variant:
        raise ContractError('extended scenario drift')
    controller = row['controller_input']
    if set(controller) != {'schema', 'bundle'} or controller['schema'] != 'extended-exploration-controller-v1':
        raise ContractError('extended caller controller required')
    bundle = FrozenRecord.from_dict(controller['bundle']); task = workflow.session.task
    if extended_exploration_injection(cell.coverage_id, cell.variant, task=FrozenRecord.from_dict(task.data()), evidence=bundle) != controller:
        raise ContractError('extended caller material reconstruction failed')
    if row['base'] != {'task': task.content_hash, 'evidence': bundle.content_hash, 'budget': bundle.data()['budget_digest']}:
        raise ContractError('extended task or budget binding drift')
    if row['controls'] != {'same_task': True, 'same_evidence': True, 'same_budget': True} or any(type(x) is not bool for x in row['controls'].values()):
        raise ContractError('extended paired controls invalid')
    return bundle, bundle.data()['materials'][cell.coverage_id][cell.variant]


class _Ledger:
    def __init__(self, workflow, experiment):
        self.workflow, self.limit, self.used = workflow, LIMITS[experiment][2], 0
        workflow.session._record('extended_exploration_allocation', {'model_calls': LIMITS[experiment][0],
            'execution_opportunities': LIMITS[experiment][1], 'verification_calls': self.limit})

    def call(self, port, subject, observation=False):
        if self.used >= self.limit:
            raise ContractError('extended verification allocation exhausted')
        self.used += 1
        common = {'attempt': self.used, 'subject_digest': subject.content_hash, 'subject': subject.data(),
            'kind': 'observation' if observation else 'preflight', 'cost': {'unit': 'verifier_units', 'units': None}}
        self.workflow.session._record('extended_verifier_request', common)
        raw = None
        try:
            raw = getattr(port, 'verify_observation' if observation else 'verify_preflight')(subject)
            if not isinstance(raw, FrozenRecord): raise ContractError('frozen verified response required')
            self.workflow.session._record('extended_verifier_response', {'attempt': self.used, 'receipt': raw.data()})
            body = raw.data(); facets = body.pop('facets', None) if observation else None
            row = _verified(FrozenRecord.from_dict(body), subject, observation=observation)
            if observation:
                if not isinstance(facets, dict) or set(facets) != set(FACETS) or any(facets[k] not in allowed for k, allowed in FACETS.items()):
                    raise ContractError('extended observation facets invalid')
                row['facets'] = facets
            self.workflow.session._record('extended_verifier_result', {**common, 'cost': row['cost'], 'receipt_digest': raw.content_hash})
            return row, raw.content_hash
        except Exception as exc:
            partial = getattr(exc, 'partial_response', None)
            if isinstance(partial, FrozenRecord):
                self.workflow.session._record('extended_verifier_partial_response', {**common, 'receipt': partial.data()})
            reported = getattr(exc, 'cost', None)
            if isinstance(reported, FrozenRecord): reported = reported.data()
            if not isinstance(reported, Mapping) or set(reported) != {'unit', 'units'} or reported['unit'] != 'verifier_units' or (reported['units'] is not None and (type(reported['units']) is not int or reported['units'] < 0)):
                reported = None
            self.workflow.session._record('extended_verifier_failure', {**common, 'error_type': type(exc).__name__,
                'reported_cost': raw.data().get('cost') if isinstance(raw, FrozenRecord) else partial.data().get('cost') if isinstance(partial, FrozenRecord) else None,
                'exception_reported_cost': dict(reported) if reported is not None else None})
            raise


def _execute_job(driver, workflow, bundle, item, job, prospective, ledger, index, role):
    template = {**item, 'original_requirements': {'execution_units': LIMITS[driver.experiment_id][1], 'token_units': LIMITS[driver.experiment_id][1]},
        'diagnostic_scope': 'measurement'}
    subject = _subject(workflow, bundle, template, job, prospective)
    subject = FrozenRecord.from_dict({**subject.data(), 'extended_config': item['config'], 'execution_index': index, 'job_role': role})
    pre, pre_hash = ledger.call(driver.authority, subject)
    permitted = item['hard_constraint'] == 'none' and all(pre['facts'][k] for k in ('safe', 'authorized', 'resources_available', 'diagnostic_inputs_available'))
    if not permitted:
        workflow.session._record('extended_job_blocked', {'execution_index': index, 'role': role, 'preflight_digest': pre_hash})
        return {'role': role, 'job_id': job['diagnostic_id'], 'status': 'blocked', 'preflight_digest': pre_hash}, None, None
    prepared = _prepare_inputs(workflow, bundle=bundle, item=job, broker=driver.broker, resolver=driver.input_resolver)
    workflow.session._record('extended_execution_reservation', {'execution_index': index, 'requirements': job['requirements'], 'role': role})
    execution, _artifacts = _execute(workflow, item=job, broker=driver.broker, prepared=prepared)
    observed = FrozenRecord.from_dict({**subject.data(), 'preflight_receipt_digest': pre_hash,
        'execution_digest': execution.content_hash, 'execution_status': execution.status, 'execution_observation': _execution_public(execution),
        'trusted_execution_material': _trusted_execution_material(workflow, bundle, job, driver, execution)})
    post, post_hash = ledger.call(driver.authority, observed, True)
    if not post['facts']['resource_request_verified']:
        raise ContractError('executed resource request not verified')
    audits = [FrozenRecord.from_dict(x) for x in post['audits']]
    verified = workflow.session.verifier.verify_evidence(audits, identity=workflow.session.task.identity,
        objective_digest=workflow.session.objective.content_hash, execution=execution, required_audit=workflow.session.required_audit).data()
    if verified['state']['validity'] == 'valid' and (post['facets']['mechanical_status'] != 'passed' or post['facets']['semantic_status'] != 'passed'):
        raise ContractError('contract success without semantic qualification cannot admit science')
    status = post['facts']['scientific_status']
    if status.startswith('qualified_') and (verified['state']['validity'] != 'valid' or status != 'qualified_' + verified['outcome'] or
            verified['state']['support'] != {'positive': 'supported', 'negative': 'refuted'}.get(verified['outcome'])):
        raise ContractError('qualified observation conflicts with verified audit state')
    if not status.startswith('qualified_') and verified['state']['validity'] == 'valid':
        raise ContractError('unqualified observation cannot admit scientific validity')
    facets = post['facets']
    if facets['diagnostic_value'] in ('effective', 'waste') and (role != 'diagnostic' or facets['mechanical_status'] != 'passed'):
        raise ContractError('diagnostic utility requires a measured diagnostic role')
    if facets['main_progress'] == 'completed' and (role != 'main' or facets['mechanical_status'] != 'passed' or facets['semantic_status'] != 'passed'):
        raise ContractError('main progress requires a qualified main observation')
    # Q7.6's independent reviewer must not inherit a root containing the
    # authority's scientific verdict. Fixed P0 admission follows its response.
    admission = None if driver.experiment_id == 'Q7.6' else workflow.session.admit(execution.content_hash, audits).data()
    return {'role': role, 'job_id': job['diagnostic_id'], 'status': execution.status,
            'execution': _execution_public(execution), 'facets': post['facets'], 'observation_digest': post_hash,
            'admission': admission, 'scientific_status': post['facts']['scientific_status']}, execution, post


def _candidate_jobs(item, experiment, enabled):
    cfg = item['config']
    if experiment == 'Q7.3':
        percent = cfg['exploration_percent'] if 'M7' in enabled else cfg['control_percent']
        units = ceil(4 * percent / 100)
        after = ExplorationBudget(4, 4).reserve(units, units).reserve(4 - units, 4 - units)
        return [(v, 'diagnostic') for v in cfg['diagnostic_ids'][:units]] + [(v, 'main') for v in cfg['main_ids'][:4-units]], {
            'ratio_id': cfg['ratio_id'], 'requested_percent': cfg['exploration_percent'], 'effective_percent': units * 25,
            'diagnostic_units': units, 'main_units': 4-units, 'budget_after': after.__dict__}
    if experiment == 'Q7.4':
        return [(cfg['old_id'], 'old_instrument'), (cfg['repair_id'] if 'M7' in enabled else cfg['old_id'], 'followup_instrument')], None
    return [(cfg['observation_id'], 'observation')], None


def _run(driver, workflow, *, cell, scenario, model):
    bundle, item = _bound(workflow, cell, scenario)
    if not all(callable(getattr(driver.authority, name, None)) for name in ('verify_preflight', 'verify_observation')):
        raise ContractError('extended trusted verification ports required')
    if item['hard_constraint'] == 'none':
        for job in item['jobs']:
            _prepare_inputs(workflow, bundle=bundle, item=job, broker=driver.broker, resolver=driver.input_resolver)
    ledger = _Ledger(workflow, driver.experiment_id)
    if driver.experiment_id == 'Q7.3':
        workflow.session._record('extended_ratio_selection_plan', freeze_ratio_selection(workflow.session.task, bundle).data())
    prospective = _invoke(workflow, cell, model, 'prospective',
        'Freeze your prospective assessment and rationale before observations. Return assessment and rationale. '
        'No engineering execution or permission by itself establishes scientific validity.',
        {'public_material': {'issue': item['public_issue'], 'jobs': item['jobs'], 'config': item['config']}})
    if set(prospective.data()) != {'assessment', 'rationale'}:
        raise ContractError('prospective schema invalid')
    for v in prospective.data().values(): required_text(v, 'prospective text')
    selected, allocation = _candidate_jobs(item, driver.experiment_id, workflow.enabled)
    workflow.session._record('extended_selected_schedule', {'jobs': selected, 'allocation': allocation, 'prospective_digest': prospective.content_hash})
    jobs = {x['diagnostic_id']: x for x in item['jobs']}; observations = []; executions = []; posts = []
    for index, (identifier, role) in enumerate(selected):
        observation, execution, post = _execute_job(driver, workflow, bundle, item, jobs[identifier], prospective, ledger, index, role)
        observations.append(observation); executions.append(execution); posts.append(post)
    operation = {}; cfg = item['config']
    if driver.experiment_id == 'Q7.3':
        operation['ratio_measurement'] = {'identity': workflow.session.task.identity.data(), 'task_digest': workflow.session.task.content_hash,
            'bundle_digest': bundle.content_hash, 'allocation': allocation,
            'effective_diagnostics': sum(o.get('facets', {}).get('diagnostic_value') == 'effective' for o in observations),
            'waste': sum(o.get('facets', {}).get('diagnostic_value') == 'waste' for o in observations),
            'unknown_diagnostics': sum(o['role'] == 'diagnostic' and o.get('facets', {}).get('diagnostic_value', 'unknown') == 'unknown' for o in observations),
            'main_completed': sum(o.get('facets', {}).get('main_progress') == 'completed' for o in observations),
            'observation_digests': [o.get('observation_digest') for o in observations], 'execution_count': sum(x is not None for x in executions)}
    elif driver.experiment_id == 'Q7.4' and executions[0] is not None:
        old, new = executions
        old_invalid = observations[0]['facets']['old_instrument_status'] == 'invalid'
        repair = InstrumentRepair(cfg['instrument_id'], jobs[cfg['old_id']]['program_sha256'], jobs[cfg['repair_id']]['program_sha256'], (old.content_hash,)) if 'M1' in workflow.enabled and old_invalid else None
        # Fixed P0 rejects known-invalid observations in both arms. M1 adds the
        # explicit repair provenance and never retroactively changes admission.
        operation['instrument_repair'] = {'old_execution': old.content_hash,
            'new_execution': new.content_hash if new else None, 'repair': repair.__dict__ if repair else None,
            'old_active_admitted': workflow.session.evidence.is_active_admitted(workflow.session.admission_roots[old.content_hash]),
            'old_requires_new_execution': repair.requires_new_execution(old.content_hash) if repair else None}
    elif driver.experiment_id == 'Q7.5' and executions[0] is not None:
        observation = observations[0]; admission = observation['admission']; root = workflow.session.admission_roots[executions[0].content_hash]
        if 'M2' in workflow.enabled:
            bindings = {'task': workflow.session.task.identity.task_id, 'objective': workflow.session.objective.content_hash}
            claim = workflow.session.claims.create(cfg['observation_claim'], subject_bindings=bindings)
            update = {'subject_bindings': bindings, 'supports': [root] if admission['admitted'] and admission['state']['support'] == 'supported' else [],
                      'refutes': [root] if admission['admitted'] and admission['state']['support'] == 'refuted' else []}
            claim = workflow.session.claims.apply(claim.claim_id, update, expected_revision=claim.revision).claim
            novelty = workflow.session.claims.create(cfg['novelty_claim'], subject_bindings=bindings)
            if observation['facets']['prior_art_status'] == 'matched':
                prior = workflow.session.evidence.append({'kind': 'bibliographic', 'root_material': {'observation_digest': observation['observation_digest']},
                    'representation': 'raw', 'content': {'prior_art_status': 'matched'}, 'subject_bindings': bindings,
                    'independent_group': item['authority_contract']['authorities'][0]['source_group']},
                    {'trusted_validator': '+'.join(admission['authorities']), 'validator_verified': True, 'admitted': True})
                novelty = workflow.session.claims.apply(novelty.claim_id, {'subject_bindings': bindings, 'supports': [], 'refutes': [prior.root_id]}, expected_revision=novelty.revision).claim
            operation['claims'] = {'observation': claim.data(), 'novelty': novelty.data(),
                'measurement_root_retained': workflow.session.evidence.is_active_admitted(root)}
    review_response = None
    if driver.experiment_id == 'Q7.6':
        public_review = {'theory': cfg['theory'], 'construct': cfg['construct'],
            'observation': observations[0].get('execution'), 'mechanical_status': observations[0].get('facets', {}).get('mechanical_status', 'unknown')}
        if 'M5' in workflow.enabled:
            review = workflow.reviews.open(task_binding=workflow.session.task.content_hash, evidence_snapshot=FrozenRecord.from_dict(public_review).content_hash,
                roles=[{'role_id': 'semantic', 'question': 'Does this observation bear on the frozen construct and theory?'}], budget_units=1)
        else:
            public_review['earlier_assessment'] = prospective.data()
        review_response = _invoke(workflow, cell, model, 'semantic_review',
            'Review construct relevance. Return assessment (accept/concern/unknown), evidence_refs, counterexamples and uncertainty. '
            'Mechanical contract success alone does not establish scientific truth.', public_review)
        ReviewEngine._response(review_response.data())
        if 'M5' in workflow.enabled:
            submitted = workflow.reviews.submit(review.review_id, role_id='semantic', reviewer_id='caller-semantic-reviewer', response=review_response.data(), cost_units=1)
            revealed = workflow.reviews.reveal(review.review_id)
            operation['semantic_review'] = {'sealed_response_digest': submitted.before_hash, 'response': revealed[0].response.data()}
        else:
            operation['semantic_review'] = {'response': review_response.data()}
        if executions[0] is not None:
            observations[0]['admission'] = workflow.session.admit(executions[0].content_hash,
                [FrozenRecord.from_dict(x) for x in posts[0]['audits']]).data()
    public_observations = []
    for observation, execution in zip(observations, executions):
        public = {k: observation[k] for k in ('role', 'job_id', 'status')}
        public['execution'] = observation.get('execution')
        if execution is not None and 'M1' in workflow.enabled:
            admission = observation['admission']; state = ScientificState(**admission['state'])
            gate = EvidenceAdmission.decide(identity=workflow.session.task.identity, state=state, outcome=admission['outcome'], execution_success=execution.status == 'succeeded',
                trusted_validator='+'.join(admission['authorities']), validator_verified=True, evidence_ids=[execution.content_hash],
                subject_bindings={'task': workflow.session.task.content_hash}, required_audit=workflow.session.required_audit,
                audit=[AuditItem(**x) for x in admission['audit']])
            public['scientific_gate'] = {'state': state.__dict__, 'admitted': gate.admitted, 'outcome': gate.outcome,
                'scientific_status': observation['scientific_status']}
        public_observations.append(public)
    context = {'observations': public_observations, 'operation': operation, 'prospective': prospective.data()}
    stage = workflow._trace('stage_3', 'executed', experiment=driver.experiment_id, operation=operation,
        observation_digests=[o.get('observation_digest') for o in observations], verification_calls=ledger.used)
    diagnostic = _invoke(workflow, cell, model, 'diagnostic', 'Reassess only the available observations and module operations. Return assessment and rationale; preserve unknown and conflicting states.', context)
    if set(diagnostic.data()) != {'assessment', 'rationale'}:
        raise ContractError('extended diagnostic judgement invalid')
    for value in diagnostic.data().values(): required_text(value, 'diagnostic text')
    workflow.session._record('extended_judgement_observed', {'judgement': diagnostic.data(), 'operation': operation})
    p0 = [{'execution_digest': execution.content_hash,
           'admission': {key: observation['admission'][key] for key in ('admitted', 'state', 'outcome')}}
          for observation, execution in zip(observations, executions) if execution is not None]
    final = _invoke(workflow, cell, model, 'final', 'Return the standard candidate with required_objective_digest and programme_complete=false. '
        'Only fixed-P0 qualified evidence may support positive/negative. Do not revive old invalid measurements or convert novelty/investment into validity.',
        {**context, 'diagnostic': diagnostic.data(), 'p0_evidence': p0})
    responses = (prospective, review_response, diagnostic, final) if review_response else (prospective, diagnostic, final)
    return stage, final, responses


@dataclass(frozen=True)
class ExtendedExplorationDriver:
    broker: object
    input_resolver: object
    authority: object
    experiment_id: str
    slots: tuple = ('prospective', 'semantic_review', 'diagnostic', 'final')
    docker_execution: str = 'matched_source_bound_extended_exploration'
    @property
    def execution_limit(self): return LIMITS[self.experiment_id][1]
    def slots_for(self, cell):
        return self.slots if self.experiment_id == 'Q7.6' else ('prospective', 'diagnostic', 'final')
    def run(self, workflow, *, cell, scenario, model, package):
        return _run(self, workflow, cell=cell, scenario=scenario, model=model)


def install_drivers(target, *, broker, input_resolver, authority):
    target.update({key: ExtendedExplorationDriver(broker, input_resolver, authority, key) for key in VARIANTS})
    return target


def freeze_ratio_selection(task, bundle):
    """A fixed train criterion, recorded before the first prospective call."""
    task.identity.require_train()
    if bundle.data()['identity'] != task.identity.data() or bundle.data()['payload_digest'] != task.payload.content_hash:
        raise ContractError('ratio selection source mismatch')
    return FrozenRecord.from_dict({'schema': 'extended-ratio-selection-plan-v1', 'identity': task.identity.data(),
        'task_digest': task.content_hash, 'bundle_digest': bundle.content_hash,
        'ratio_ids': sorted(x['config']['ratio_id'] for x in bundle.data()['materials']['Q7.3'].values()),
        'criterion': 'main_completed_plus_effective_minus_waste', 'tie_break': 'lower_exploration_then_ratio_id',
        'missing_or_unknown': 'no_selection', 'required_arms': ['M7_off', 'M7_on']})


def select_training_ratio(*, task, bundle, panel, runtimes):
    """Select only from a complete, verified caller-owned execution journal.

    Trace integrity is an engineering trust boundary, not an independent proof
    that the caller's scientific observation authority is correct. Utility
    comes from that authority's bound receipts, never container exit status.
    """
    from research_loop.modular.panel_receipts import PanelReceiptVerifier
    import json
    plan = freeze_ratio_selection(task, bundle)
    if panel.domain != 'train': raise ContractError('ratio optimization is train-only')
    PanelReceiptVerifier().verify(panel, tuple(runtimes))
    cells = {cell.key: cell for cell in panel.cells}
    expected = [cell for cell in panel.cells if cell.coverage_id == 'Q7.3' and cell.task_digest == task.content_hash]
    if len(expected) != 8 or {cell.variant for cell in expected} != set(VARIANTS['Q7.3']):
        raise ContractError('ratio selection requires all four ratios and both arms once')
    rows = []
    for runtime in runtimes:
        # The panel verifier has already checked exact receipt/cell ownership.
        cell = cells[runtime.cell_key]
        if cell not in expected: continue
        events = [json.loads(line) for line in runtime.trace_path.read_text(encoding='utf-8').splitlines()]
        frozen = [i for i, event in enumerate(events) if event['stage'] == 'extended_ratio_selection_plan']
        calls = [i for i, event in enumerate(events) if event['stage'] == 'model_request']
        if len(frozen) != 1 or not calls or frozen[0] >= calls[0] or events[frozen[0]]['data'] != plan.data():
            raise ContractError('ratio criterion was not frozen before observation')
        item = bundle.data()['materials']['Q7.3'][cell.variant]
        schedule, allocation = _candidate_jobs(item, 'Q7.3', cell.runtime_arm.data()['enabled'])
        requests = {event['data']['attempt']: event['data'] for event in events if event['stage'] == 'extended_verifier_request'}
        responses = [event['data'] for event in events if event['stage'] == 'extended_verifier_response']
        metrics = {'effective_diagnostics': 0, 'waste': 0, 'main_completed': 0, 'unknown': 0}
        digests = []
        for response in responses:
            request = requests[response['attempt']]
            if request['kind'] != 'observation': continue
            subject = FrozenRecord.from_dict(request['subject']); body = response['receipt'].copy(); facets = body.pop('facets')
            _verified(FrozenRecord.from_dict(body), subject, observation=True)
            data = subject.data(); index = data['execution_index']
            if data['task_digest'] != task.content_hash or data['bundle_digest'] != bundle.content_hash or (data['diagnostic']['diagnostic_id'], data['job_role']) != schedule[index]:
                raise ContractError('ratio observation subject or schedule drift')
            metrics['effective_diagnostics'] += facets['diagnostic_value'] == 'effective'
            metrics['waste'] += facets['diagnostic_value'] == 'waste'
            metrics['main_completed'] += facets['main_progress'] == 'completed'
            metrics['unknown'] += (facets['diagnostic_value'] == 'unknown' if data['job_role'] == 'diagnostic' else facets['main_progress'] == 'unknown')
            digests.append(FrozenRecord.from_dict(response['receipt']).content_hash)
        complete = len(digests) == 4 and len(set(digests)) == 4 and runtime.status == 'succeeded' and metrics['unknown'] == 0
        rows.append({'ratio_id': allocation['ratio_id'], 'enabled': 'M7' in cell.runtime_arm.data()['enabled'],
            'exploration_percent': item['config']['exploration_percent'], 'allocation': allocation, **metrics,
            'complete': complete, 'observation_digests': digests, 'trace_digest': runtime.trace_digest})
    if len(rows) != 8: raise ContractError('ratio denominator incomplete')
    selected = None
    if all(row['complete'] for row in rows):
        candidates = [row for row in rows if row['enabled']]
        selected = min(candidates, key=lambda row: (-(row['main_completed'] + row['effective_diagnostics'] - row['waste']), row['exploration_percent'], row['ratio_id']))['ratio_id']
    return FrozenRecord.from_dict({'schema': 'extended-ratio-selection-result-v1', 'plan_digest': plan.content_hash,
        'identity': task.identity.data(), 'rows': rows, 'selected_ratio_id': selected,
        'status': 'selected_on_train' if selected is not None else 'unresolved', 'scientific_efficacy_established': False})
