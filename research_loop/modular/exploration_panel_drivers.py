"""Caller-bound Q7.1/Q7.2 production drivers. No source truth is variant-derived."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Protocol

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text, strict_bool
from research_loop.modular.feasibility_panel_drivers import (
    _map, _hex, _inputs, _prepare_inputs, _execute, _execution_public, _invoke,
)
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ExplorationPolicy, ScientificState
from research_loop.modular.modules.exploration import (
    Appeal, ExplorationBudget, ExplorationPlan, ResourceClosure, Veto, review_appeal,
    select_claimed_diagnostic,
)
from research_loop.ontology import ContractError

Q71_VARIANTS = ('low_cost', 'data_unknown', 'measurement_repair', 'valid_negative', 'conflict')
Q72_VARIANTS = ('deterministic', 'insufficient', 'value')
BUDGET = {'model_calls': 3, 'execution_opportunities': 1, 'verification_calls': 2}


class ExplorationAuthorityPort(Protocol):
    """Caller-owned verification, with observation sources outside solver context."""
    def verify_preflight(self, subject: FrozenRecord) -> FrozenRecord: ...
    def verify_observation(self, subject: FrozenRecord) -> FrozenRecord: ...


def _requirements(raw):
    value = dict(_map(raw, 'resource requirements'))
    if set(value) != {'execution_units', 'token_units'} or any(type(v) is not int or v < 0 for v in value.values()):
        raise ContractError('resource requirements need nonnegative integer units')
    return value


def _diagnostic(raw, task):
    import hashlib
    import os
    from pathlib import Path
    from research_loop.modular.benchmarks.execution import ExecutionRequest
    value = dict(_map(raw, 'bounded diagnostic'))
    expected = {'diagnostic_id', 'program', 'program_sha256', 'image', 'inputs', 'requirements',
                'subjective_score', 'uncertainty_reduction', 'measurement_contract'}
    if set(value) != expected:
        raise ContractError('diagnostic fields incomplete')
    for key in ('diagnostic_id', 'program', 'image'):
        required_text(value[key], key)
    if '\r' in value['program'] or hashlib.sha256(value['program'].replace('\n', os.linesep).encode()).hexdigest() != _hex(value['program_sha256'], 'program hash'):
        raise ContractError('diagnostic literal program hash mismatch')
    ExecutionRequest(task.identity, value['image'], Path('unresolved.py'), {'public': Path('unresolved.csv')})
    value['inputs'] = _inputs(value['inputs'])
    value['requirements'] = _requirements(value['requirements'])
    if value['requirements']['execution_units'] != 1:
        raise ContractError('one bounded execution is required per diagnostic')
    if any(type(value[k]) is not int or value[k] < 0 for k in ('subjective_score', 'uncertainty_reduction')):
        raise ContractError('prospective diagnostic estimates must be nonnegative integers')
    contract = dict(_map(value['measurement_contract'], 'measurement contract'))
    if set(contract) != {'contract_id', 'source_id', 'data_version', 'observable', 'negative_control_id'}:
        raise ContractError('measurement contract is not closed')
    if contract['source_id'] != task.identity.group_id or contract['data_version'] != task.identity.dataset_version:
        raise ContractError('measurement source or version drift')
    for key in contract:
        required_text(contract[key], key)
    value['measurement_contract'] = contract
    return value


def _item(raw, task, appeal):
    value = dict(_map(raw, 'exploration material'))
    fields = {'source_id', 'data_version', 'public_issue', 'diagnostic_scope', 'original_requirements',
              'declared_state', 'diagnostics', 'authority_contract', 'hard_constraint'}
    if appeal:
        fields.add('veto')
    if set(value) != fields or value['source_id'] != task.identity.group_id or value['data_version'] != task.identity.dataset_version:
        raise ContractError('exploration source, version or fields drift')
    required_text(value['public_issue'], 'public issue')
    if value['diagnostic_scope'] not in ('data_check', 'measurement', 'instrument_repair') or value['hard_constraint'] not in ('none', 'authorization', 'resource', 'contract'):
        raise ContractError('diagnostic scope or hard constraint invalid')
    value['declared_state'] = ScientificState(**dict(_map(value['declared_state'], 'declared state'))).__dict__
    value['original_requirements'] = _requirements(value['original_requirements'])
    if not isinstance(value['diagnostics'], list) or len(value['diagnostics']) != 2:
        raise ContractError('two caller-frozen diagnostic alternatives required')
    value['diagnostics'] = [_diagnostic(row, task) for row in value['diagnostics']]
    if len({row['diagnostic_id'] for row in value['diagnostics']}) != 2:
        raise ContractError('diagnostic identities must differ')
    for row in value['diagnostics']:
        req, original = row['requirements'], value['original_requirements']
        if any(req[k] > original[k] for k in req) or sum(req.values()) >= sum(original.values()):
            raise ContractError('each diagnostic must use strictly smaller frozen resources')
    contract = dict(_map(value['authority_contract'], 'authority contract'))
    if set(contract) != {'contract_id', 'source_id', 'authorities'} or contract['source_id'] != task.identity.group_id:
        raise ContractError('authority contract source drift')
    required_text(contract['contract_id'], 'authority contract id')
    authorities = contract['authorities']
    if not isinstance(authorities, list) or len(authorities) != 2:
        raise ContractError('two independent observation authorities required')
    for row in authorities:
        if not isinstance(row, Mapping) or set(row) != {'authority_id', 'source_group'}:
            raise ContractError('authority source fields incomplete')
        for val in row.values():
            required_text(val, 'authority identity')
    if len({r['authority_id'] for r in authorities}) != 2 or len({r['source_group'] for r in authorities}) != 2 or task.identity.group_id in {r['source_group'] for r in authorities}:
        raise ContractError('independent fixture observation sources must be distinct')
    value['authority_contract'] = contract
    if appeal:
        veto = dict(_map(value['veto'], 'original veto'))
        if set(veto) != {'kind', 'reason', 'evidence_digest'}:
            raise ContractError('veto must bind original evidence')
        Veto(**veto)
        _hex(veto['evidence_digest'], 'original veto evidence')
    return value


def freeze_exploration_panel_bundle(task: PublicTask, *, q71: Mapping, q72: Mapping, budget: FrozenRecord) -> FrozenRecord:
    if not isinstance(task, PublicTask) or not isinstance(budget, FrozenRecord) or budget.data() != BUDGET:
        raise ContractError('exploration requires caller-bound public task and matched opportunity budget')
    task.identity.require_train()
    if set(q71) != set(Q71_VARIANTS) or set(q72) != set(Q72_VARIANTS):
        raise ContractError('exploration variant coverage mismatch')
    return FrozenRecord.from_dict({'schema': 'exploration-panel-bundle-v1', 'identity': task.identity.data(),
        'payload_digest': task.payload.content_hash, 'budget': budget.data(), 'budget_digest': budget.content_hash,
        'q71': {key: _item(row, task, False) for key, row in q71.items()},
        'q72': {key: _item(row, task, True) for key, row in q72.items()}})


def exploration_panel_injection(experiment_id, variant, *, task, evidence):
    public = PublicTask(DataIdentity.parse(task.data()['identity']), FrozenRecord.from_dict(task.data()['payload']))
    raw = evidence.data()
    bundle = freeze_exploration_panel_bundle(public, q71=raw.get('q71', {}), q72=raw.get('q72', {}), budget=FrozenRecord.from_dict(raw.get('budget', {})))
    key = 'q71' if experiment_id == 'Q7.1' else 'q72' if experiment_id == 'Q7.2' else None
    if bundle.content_hash != evidence.content_hash or key is None or variant not in raw[key]:
        raise ContractError('exploration bundle or variant binding mismatch')
    return {'schema': 'exploration-panel-controller-v1', 'bundle': bundle.data()}


def _material(workflow, cell, scenario):
    row = scenario.data()
    if set(row) != {'experiment_id', 'variant', 'controller_input', 'base', 'controls'} or row['experiment_id'] != cell.coverage_id or row['variant'] != cell.variant:
        raise ContractError('scenario subject drift')
    controller = row['controller_input']
    if set(controller) != {'schema', 'bundle'} or controller['schema'] != 'exploration-panel-controller-v1':
        raise ContractError('caller exploration controller required')
    bundle = FrozenRecord.from_dict(controller['bundle'])
    task = workflow.session.task
    injection = exploration_panel_injection(cell.coverage_id, cell.variant, task=FrozenRecord.from_dict(task.data()), evidence=bundle)
    if injection != controller or row['base'] != {'task': task.content_hash, 'evidence': bundle.content_hash, 'budget': bundle.data()['budget_digest']}:
        raise ContractError('scenario task, source or budget drift')
    if row['controls'] != {'same_task': True, 'same_evidence': True, 'same_budget': True} or any(type(x) is not bool for x in row['controls'].values()):
        raise ContractError('paired scenario controls invalid')
    return bundle, bundle.data()['q71' if cell.coverage_id == 'Q7.1' else 'q72'][cell.variant]


def _verified(raw, subject, *, observation):
    if not isinstance(raw, FrozenRecord):
        raise ContractError('authority must return a verified frozen receipt')
    row, body = raw.data(), subject.data()
    fields = {'schema', 'subject_digest', 'observations', 'facts', 'cost'} | ({'audits'} if observation else set())
    if set(row) != fields or row['schema'] != ('exploration-observation-verified-v1' if observation else 'exploration-preflight-verified-v1') or row['subject_digest'] != subject.content_hash:
        raise ContractError('authority receipt subject mismatch')
    proofs = row['observations']; expected = body['authority_contract']['authorities']
    if not isinstance(proofs, list) or len(proofs) != 2:
        raise ContractError('two verified observation sources required')
    by_id = {x['authority_id']: x['source_group'] for x in expected}
    seen = set(); hashes = set()
    for proof in proofs:
        if set(proof) != {'authority_id', 'source_group', 'subject_digest', 'contract_id', 'observation_digest', 'signature_verified'}:
            raise ContractError('observation proof fields invalid')
        aid = proof['authority_id']
        if aid not in by_id or aid in seen or proof['source_group'] != by_id[aid] or proof['subject_digest'] != subject.content_hash or proof['contract_id'] != body['authority_contract']['contract_id']:
            raise ContractError('observation source or subject drift')
        if strict_bool(proof['signature_verified'], 'signature verified') is not True:
            raise ContractError('authority signature failed')
        seen.add(aid); hashes.add(_hex(proof['observation_digest'], 'observation hash'))
    if len(hashes) != 2:
        raise ContractError('independent observation digests collapsed')
    cost = row['cost']
    if set(cost) != {'unit', 'units'} or cost['unit'] != 'verifier_units' or (cost['units'] is not None and (type(cost['units']) is not int or cost['units'] < 0)):
        raise ContractError('verifier cost invalid')
    facts = row['facts']
    expected_facts = ({'block_status', 'resource_request_verified', 'diagnostic_answer'} if observation else
                      {'safe', 'authorized', 'resources_available', 'diagnostic_inputs_available', 'scientific_data_status', 'block_status'})
    if set(facts) != expected_facts or facts['block_status'] not in ('blocked', 'cleared', 'unknown'):
        raise ContractError('authority facts invalid')
    if observation:
        strict_bool(facts['resource_request_verified'], 'resource request verified')
        if facts['diagnostic_answer'] not in ('repair_supported', 'no_repair', 'inconclusive') or not isinstance(row['audits'], list) or len(row['audits']) != 2:
            raise ContractError('diagnostic result or audit pair incomplete')
    else:
        for key in ('safe', 'authorized', 'resources_available', 'diagnostic_inputs_available'):
            strict_bool(facts[key], key)
        if facts['scientific_data_status'] not in ('passed', 'failed', 'unknown'):
            raise ContractError('scientific data status invalid')
    return row


class _Ledger:
    def __init__(self, workflow):
        self.workflow, self.used = workflow, 0
        workflow.session._record('exploration_allocation', BUDGET)

    def call(self, port, subject, *, observation=False):
        if self.used >= BUDGET['verification_calls']:
            raise ContractError('verification budget exhausted')
        self.used += 1
        common = {'attempt': self.used, 'kind': 'observation' if observation else 'preflight',
                  'subject_digest': subject.content_hash, 'subject': subject.data(), 'cost': {'unit': 'verifier_units', 'units': None}}
        self.workflow.session._record('exploration_verifier_request', common)
        raw = None
        try:
            raw = getattr(port, 'verify_observation' if observation else 'verify_preflight')(subject)
            if isinstance(raw, FrozenRecord):
                self.workflow.session._record('exploration_verifier_response', {'attempt': self.used, 'receipt': raw.data()})
            row = _verified(raw, subject, observation=observation)
            self.workflow.session._record('exploration_verifier_result', {**common, 'cost': row['cost'], 'receipt_digest': raw.content_hash})
            return row, raw.content_hash
        except Exception as exc:
            self.workflow.session._record('exploration_verifier_failure', {**common, 'error_type': type(exc).__name__,
                'reported_cost': raw.data().get('cost') if isinstance(raw, FrozenRecord) else None})
            raise


def _subject(workflow, bundle, item, chosen, prospective):
    return FrozenRecord.from_dict({'schema': 'exploration-authority-subject-v1',
        'identity': workflow.session.task.identity.data(), 'task_digest': workflow.session.task.content_hash,
        'objective_digest': workflow.session.objective.content_hash, 'bundle_digest': bundle.content_hash,
        'source_id': item['source_id'], 'data_version': item['data_version'], 'authority_contract': item['authority_contract'],
        'veto': item.get('veto'), 'hard_constraint': item['hard_constraint'], 'diagnostic_scope': item['diagnostic_scope'],
        'original_requirements': item['original_requirements'], 'diagnostic': chosen,
        'prospective_digest': prospective.content_hash})


def _run(driver, workflow, *, cell, scenario, model):
    bundle, item = _material(workflow, cell, scenario)
    if not all(callable(getattr(driver.authority, method, None)) for method in ('verify_preflight', 'verify_observation')):
        raise ContractError('caller trusted verification ports are required')
    ledger = _Ledger(workflow)
    public = {key: item[key] for key in ('public_issue', 'diagnostic_scope', 'original_requirements', 'diagnostics', 'hard_constraint')}
    if 'veto' in item:
        public['veto'] = item['veto']
    prospective = _invoke(workflow, cell, model, 'prospective',
        'Freeze a prospective assessment before any observed result. Select one public diagnostic_id and return '
        'exploration_allowed (boolean), evidence_qualified (boolean), decision (explore/repair/block/defer), and rationale. '
        'A diagnostic opportunity never establishes scientific evidence.', {'public_material': public})
    proposal = prospective.data()
    if set(proposal) != {'diagnostic_id', 'exploration_allowed', 'evidence_qualified', 'decision', 'rationale'} or proposal['decision'] not in ('explore', 'repair', 'block', 'defer'):
        raise ContractError('prospective judgement invalid')
    for key in ('exploration_allowed', 'evidence_qualified'):
        strict_bool(proposal[key], key)
    required_text(proposal['rationale'], 'prospective rationale')
    choices = {x['diagnostic_id']: x for x in item['diagnostics']}
    if proposal['diagnostic_id'] not in choices:
        raise ContractError('unregistered diagnostic selection')
    selected = proposal['diagnostic_id']
    original = item['original_requirements']
    first = choices[selected]
    plan = ExplorationPlan('exploration-' + bundle.content_hash, workflow.session.task.identity, bundle,
        ResourceClosure(item['data_version'], first['program_sha256'], first['measurement_contract']['negative_control_id'], **original))
    if 'M7' in workflow.enabled:
        policy = FrozenRecord.from_dict({'policy_version': 'frozen-exploration-v1', 'identity': workflow.session.task.identity.data(),
            'criterion': 'uncertainty_per_cost', 'frozen_before_validation': False})
        candidates = tuple(FrozenRecord.from_dict({'diagnostic_id': x['diagnostic_id'], 'subjective_score': x['subjective_score'],
            'uncertainty_reduction': x['uncertainty_reduction'], 'cost': sum(x['requirements'].values())}) for x in choices.values())
        selected = select_claimed_diagnostic(plan, policy, candidates).data()['diagnostic_id']
    chosen = choices[selected]
    subject = _subject(workflow, bundle, item, chosen, prospective)
    pre, pre_digest = ledger.call(driver.authority, subject)
    facts = pre['facts']
    hard = item['hard_constraint'] in ('authorization', 'resource')
    host_allowed = not hard and all(facts[k] for k in ('safe', 'authorized', 'resources_available', 'diagnostic_inputs_available'))
    disposition = None
    if 'M7' in workflow.enabled:
        # This permit refers to the cheap diagnostic, never the original science
        # prerequisite or failed instrument. The latter states stay unchanged.
        permit = ExplorationPolicy.admit(identity=workflow.session.task.identity,
            state=ScientificState('unknown', 'undetermined', 'unknown', 'explore'),
            safe=host_allowed, budget_available=facts['resources_available'],
            subject_bindings={'task': workflow.session.task.content_hash, 'diagnostic': FrozenRecord.from_dict(chosen).content_hash},
            required_audit=('safe_diagnostic',), audit=[AuditItem('safe_diagnostic', True, host_allowed)])
        if cell.coverage_id == 'Q7.2':
            veto = Veto(**item['veto'])
            appeal = Appeal(veto, FrozenRecord.from_dict(chosen), chosen['requirements']['execution_units'],
                chosen['requirements']['token_units'], pre_digest if veto.kind == 'deterministic_block' else None)
            appeal_decision = review_appeal(plan=plan, veto=veto, appeal=appeal,
                budget=ExplorationBudget(**{'execution_limit': original['execution_units'], 'token_limit': original['token_units']}))
            disposition = {'status': appeal_decision.status, 'original_veto_digest': veto.evidence_digest,
                'preflight_digest': pre_digest, 'original_requirements': original, 'diagnostic_requirements': chosen['requirements']}
        allowed = permit.allowed
    else:
        allowed = host_allowed  # fixed safety boundary; same shadow execution opportunity
    prepared = _prepare_inputs(workflow, bundle=bundle, item=chosen, broker=driver.broker, resolver=driver.input_resolver) if allowed else None
    execution = None; post = None; admission = None; post_digest = None
    if allowed:
        workflow.session._record('exploration_execution_reservation', {'units': chosen['requirements'], 'diagnostic_digest': FrozenRecord.from_dict(chosen).content_hash})
        execution, artifacts = _execute(workflow, item=chosen, broker=driver.broker, prepared=prepared)
        post_subject = FrozenRecord.from_dict({**subject.data(), 'preflight_receipt_digest': pre_digest,
            'execution_digest': execution.content_hash, 'execution_status': execution.status,
            'execution_observation': _execution_public(execution)})
        post, post_digest = ledger.call(driver.authority, post_subject, observation=True)
        # P0 is identical in both arms. Actual signed scientific evidence and
        # execution provenance are necessary for any final positive/negative.
        audits = [FrozenRecord.from_dict(row) for row in post['audits']]
        verified = workflow.session.verifier.verify_evidence(audits, identity=workflow.session.task.identity,
            objective_digest=workflow.session.objective.content_hash, execution=execution, required_audit=workflow.session.required_audit).data()
        if post['facts']['resource_request_verified'] is not True:
            raise ContractError('actual diagnostic resource request not verified')
        admission = workflow.session.admit(execution.content_hash, audits).data()
    else:
        workflow.session._record('exploration_opportunity_blocked', {'preflight_digest': pre_digest,
            'execution_opportunities_reserved': 1, 'verification_opportunities_reserved': 2, 'actual_verification_calls': ledger.used,
            'reason': 'host_resource_authorization_safety_or_input_block'})
    evidence_gate = None
    if 'M1' in workflow.enabled and admission is not None:
        state = ScientificState(**verified['state'])
        gate = EvidenceAdmission.decide(identity=workflow.session.task.identity, state=state, outcome=verified['outcome'],
            execution_success=execution.status == 'succeeded', trusted_validator='+'.join(verified['authorities']), validator_verified=True,
            evidence_ids=[execution.content_hash], subject_bindings={'task': workflow.session.task.content_hash, 'diagnostic': subject.content_hash},
            required_audit=workflow.session.required_audit, audit=[AuditItem(**row) for row in verified['audit']])
        evidence_gate = {'state': state.__dict__, 'admitted': gate.admitted, 'outcome': gate.outcome,
                         'evidence_ids': list(gate.evidence_ids) if gate.admitted else [], 'reason': gate.reason}
    transition = None
    if 'M7' in workflow.enabled:
        if not allowed:
            status = 'block'
        elif execution.status != 'succeeded':
            status = 'block'
        elif cell.coverage_id == 'Q7.2' and item['veto']['kind'] == 'deterministic_block':
            status = 'repair' if post['facts']['block_status'] == 'cleared' and post['facts']['diagnostic_answer'] == 'repair_supported' else 'block'
        elif post['facts']['diagnostic_answer'] == 'repair_supported':
            status = 'repair'
        elif post['facts']['diagnostic_answer'] == 'inconclusive':
            status = 'defer'
        else:
            status = 'explore' if cell.coverage_id == 'Q7.1' or item['veto']['kind'] == 'value_doubt' else 'block'
        transition = {'decision': status, 'diagnostic_allowed': allowed, 'appeal': disposition,
            'original_veto': item.get('veto'), 'prior_block_status': facts['block_status'],
            'observed_block_status': post['facts']['block_status'] if post else facts['block_status'],
            'prior_evidence_digest': item.get('veto', {}).get('evidence_digest'), 'diagnostic_evidence_digest': post_digest,
            'original_requirements': original, 'diagnostic_requirements': chosen['requirements'],
            'original_prerequisite_promoted': False}
    observation = {'execution': _execution_public(execution) if execution else None,
        'host_diagnostic_allowed': host_allowed, 'selected_diagnostic_id': selected,
        'scientific_data_status': facts['scientific_data_status'], 'prospective': proposal,
        'evidence_gate': evidence_gate, 'exploration_transition': transition}
    stage = workflow._trace('stage_3' if 'M7' in workflow.enabled else 'operation_exploration_control', 'executed',
        prospective_digest=prospective.content_hash, preflight_digest=pre_digest, observation_digest=post_digest,
        original_requirements=original, selected_requirements=chosen['requirements'], public_observation=observation,
        verification_calls=ledger.used, exploration_never_promotes_prerequisite=True)
    diagnostic = _invoke(workflow, cell, model, 'diagnostic',
        'Reassess the original issue using the selected diagnostic and available observations. Return decision '
        '(explore/repair/block/defer), exploration_allowed (boolean), evidence_qualified (boolean), rationale. '
        'Preserve missing data, measurement repair, negative observations, and conflicts separately; exploration is not evidence admission.',
        {'observation': observation})
    decision = diagnostic.data()
    if set(decision) != {'decision', 'exploration_allowed', 'evidence_qualified', 'rationale'} or decision['decision'] not in ('explore', 'repair', 'block', 'defer'):
        raise ContractError('diagnostic judgement invalid')
    for key in ('exploration_allowed', 'evidence_qualified'):
        strict_bool(decision[key], key)
    required_text(decision['rationale'], 'diagnostic rationale')
    # Keep erroneous model judgements as observations, rather than silently
    # replacing them with expected labels or aborting their final denominator.
    workflow.session._record('exploration_judgement_observed', {'judgement': decision, 'transition': transition, 'evidence_gate': evidence_gate})
    final = _invoke(workflow, cell, model, 'final',
        'Return the standard candidate with required_objective_digest, outcome, evidence_ids, conclusion and programme_complete=false. '
        'Only P0-verified scientific observations can support positive/negative; preserve unknown/invalid when appropriate. '
        'A repaired diagnostic never retroactively qualifies prior findings.',
        {'observation': observation, 'diagnostic': decision,
         'p0_evidence': {'admitted': admission['admitted'], 'state': admission['state'], 'outcome': admission['outcome'],
                         'evidence_ids': [execution.content_hash] if admission['admitted'] else []} if admission else None})
    # No candidate rewriting or blanket unknown policy: caller runs finish on
    # this exact returned record, including blocked/incorrect candidates.
    return stage, final, (prospective, diagnostic, final)


@dataclass(frozen=True)
class Q71ExplorationAdmissionDriver:
    broker: Any
    input_resolver: Any
    authority: ExplorationAuthorityPort
    experiment_id: str = 'Q7.1'
    slots: tuple[str, ...] = ('prospective', 'diagnostic', 'final')
    execution_limit: int = 1
    docker_execution: str = 'one_matched_restricted_diagnostic_opportunity'
    def slots_for(self, cell): return self.slots
    def run(self, workflow, *, cell, scenario, model, package):
        return _run(self, workflow, cell=cell, scenario=scenario, model=model)


@dataclass(frozen=True)
class Q72FeasibilityAppealDriver(Q71ExplorationAdmissionDriver):
    experiment_id: str = 'Q7.2'


def install_drivers(target: MutableMapping[str, Any], *, broker, input_resolver, authority):
    target.update({'Q7.1': Q71ExplorationAdmissionDriver(broker, input_resolver, authority),
                   'Q7.2': Q72FeasibilityAppealDriver(broker, input_resolver, authority)})
    return target
