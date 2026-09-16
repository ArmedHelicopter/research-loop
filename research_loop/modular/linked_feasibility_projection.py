"""Replay the actual bounded feasibility driver without model, Docker or authority I/O.

Authority receipts retain the existing trusted-controller provenance boundary;
replay does not establish independent scientific validity or calibration.
"""
from pathlib import Path
from types import SimpleNamespace

from research_loop.modular.benchmarks.execution import ExecutionReceipt, DockerExecutionBroker
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.feasibility_panel_drivers import Q51FeasibilityDriver, Q52DistinguishabilityDriver, _material
from research_loop.modular.modules.context import ContextBuilder
from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.workflow import WorkflowResult
from research_loop.ontology import ContractError, canonical

R = FrozenRecord.from_dict
COVERAGE = frozenset({'Q5.1', 'Q5.2'})
STAGES = frozenset({'stage_3', 'operation_m7_control', 'm4_prediction_rejected',
                    'prediction_outcome_bound', 'feasibility_diagnostic_decision'})


class _Log:
    def __init__(self): self.rows = []
    def append(self, row): self.rows.append(R(row).data())


class _Replay:
    def __init__(self, cell, task, lock, timeline, item):
        self.cell, self.task, self.lock, self.timeline, self.item = cell, task, lock, timeline, item
        self.cursor = 0; self.requests = []; self.stages = []; self.executions = {}
        self.session = self; self.objective = R(lock.data()['objective'])
        self.enabled = frozenset(cell.runtime_arm.data()['enabled'])
        self.evidence = EvidenceLedger(task.identity); self.claims = ClaimLedger(self.evidence)
        self.predictions = PredictionRegistry(task.identity); self.predictions._log = _Log()

    def take(self, stage):
        if self.cursor >= len(self.timeline) or self.timeline[self.cursor]['stage'] != stage:
            raise ContractError('feasibility operation chronology differs from the original driver')
        data = self.timeline[self.cursor]['data']; self.cursor += 1
        return data

    def _record(self, stage, data):
        if self.take(stage) != data:
            raise ContractError('feasibility original request, response or result differs from replay')
        return R(data)

    def _trace(self, stage, status, **data):
        record = R({'stage': stage, 'status': status, **data})
        self._record('modular_workflow', record.data()); self.stages.append(record.data())
        return WorkflowResult(status, record)

    def validate_inputs(self, identity, inputs):
        if identity != self.task.identity or inputs != self.item['inputs']:
            raise ContractError('feasibility replay input binding differs')
        return tuple(SimpleNamespace(artifact_id=k, record=R({'artifact_id': k, **v}))
                     for k, v in sorted(inputs.items()))

    def execute(self, code, *, broker, image, inputs):
        if code != self.item['program'] or image != self.item['image'] or inputs != self.item['inputs']:
            raise ContractError('feasibility replay execution differs from the frozen literal')
        self._record('execution_request', {'attempt': 1, 'program_sha256': self.item['program_sha256']})
        data = self.take('execution_result'); receipt = ExecutionReceipt.parse(data['receipt'])
        if data != {'execution_digest': receipt.content_hash, 'status': receipt.status,
                    'record': receipt.record.data(), 'receipt': receipt.data()}:
            raise ContractError('feasibility execution record and receipt differ')
        self.executions[receipt.content_hash] = receipt
        return receipt

    def _authority(self, subject):
        # The native ledger immediately records the returned FrozenRecord. Do not
        # consume it here: _VerificationLedger compares all common bindings.
        if self.cursor >= len(self.timeline) or self.timeline[self.cursor]['stage'] != 'feasibility_verifier_response':
            raise ContractError('feasibility replay lacks the original authority response')
        data = self.timeline[self.cursor]['data']
        if data['subject'] != subject.data() or data['subject_digest'] != subject.content_hash:
            raise ContractError('feasibility authority response has a different subject')
        return R(data['receipt'])

    verify_stage = _authority
    verify_prediction_outcome = _authority

    def invoke_model(self, slot, model, *, instruction, module_context):
        context = ContextBuilder(self.task.identity, budget_bytes=self.lock.data()['context_budget']).build(
            canonical(self.task.payload.data()), self.evidence, self.claims,
            mode='candidate' if 'M3' in self.enabled else 'baseline', baseline_summary='').public_data()
        request = R({'schema': 'public-model-request-v1', 'task': self.task.data(),
            'lock_digest': self.lock.content_hash, 'objective': self.objective.data(), 'slot': slot,
            'instruction': instruction, 'context': context, 'module_context': module_context.data(),
            'execution_feedback': [{'id': k, 'status': e.status, 'stdout': e.record.data().get('stdout', ''),
                'stderr': e.record.data().get('stderr', '')} for k, e in self.executions.items()]})
        self._record('model_request', {'request_digest': request.content_hash, 'request': request.data()})
        response = self.take('model_response')
        if response.get('request_digest') != request.content_hash or set(response) != {'request_digest', 'response'}:
            raise ContractError('feasibility model response has a different original request')
        self.requests.append(request)
        return R(response['response'])


def derive_feasibility_replay(*, cell, task, scenario, package, events):
    if (cell.coverage_id not in COVERAGE or task.identity != cell.identity or task.content_hash != cell.task_digest
            or scenario.content_hash != cell.scenario_digest or package.digest != cell.package_digest
            or not events or events[0]['stage'] != 'objective_lock'):
        raise ContractError('feasibility replay requires its original frozen cell')
    lock = R(events[0]['data']); b = lock.data()
    if (b.get('identity') != task.identity.data() or b.get('task_digest') != task.content_hash
            or b.get('package_digest') != package.digest or b.get('arm') != cell.runtime_arm.data()
            or b.get('slots') != ['subjective', 'diagnostic', 'final'] or b.get('execution_limit') != 1):
        raise ContractError('feasibility original lock or opportunity budget differs')
    _, item = _material(task, scenario, cell.coverage_id, cell.variant)
    timeline = [{'stage': e['stage'], 'data': e['data']} for e in events if
        e['stage'] in {'model_request', 'model_response', 'model_failure', 'execution_request', 'execution_result',
                       'execution_failure', 'execution_terminal'} or e['stage'].startswith('feasibility_')
        or (e['stage'] == 'modular_workflow' and e['data'].get('stage') in STAGES)]
    replay = _Replay(cell, task, lock, timeline, item)
    driver = (Q51FeasibilityDriver if cell.coverage_id == 'Q5.1' else Q52DistinguishabilityDriver)(
        replay, lambda _task, _bundle: item['inputs'], replay)
    _stage, final, _responses = driver.run(replay, cell=cell, scenario=scenario, model=None, package=package)
    if replay.cursor != len(timeline) or [r.data()['slot'] for r in replay.requests] != list(driver.slots):
        raise ContractError('feasibility replay omitted or repeated an original operation')
    public = replay.requests[-1].data()['module_context']
    return R({'schema': 'linked-feasibility-native-replay-v1', 'cell_digest': R(cell.data()).content_hash,
        'lock': lock.data(), 'package': package.record.data(), 'timeline': timeline,
        'public_material': {'kind': 'bounded_feasibility', 'observation': public['observation'],
            'diagnostic': public['diagnostic'], 'scientific_effect': 'not_measured'},
        'final_candidate': final.data(), 'prediction_journal': replay.predictions._log.rows,
        'stages': replay.stages, 'request_digests': [r.content_hash for r in replay.requests]})


def verify_feasibility_originals(*, cell, task, scenario, package, events, sidecar):
    replay = derive_feasibility_replay(cell=cell, task=task, scenario=scenario, package=package, events=events)
    path = Path(sidecar)/'predictions.jsonl'
    if (not path.is_file() or DockerExecutionBroker._has_link_component(path)
            or path.read_bytes() != ''.join(canonical(r)+'\n' for r in replay.data()['prediction_journal']).encode()):
        raise ContractError('feasibility original prediction journal differs from replay')
    _, item = _material(task, scenario, cell.coverage_id, cell.variant)
    path = Path(sidecar)/'analysis-1.py'
    import hashlib
    if (not path.is_file() or DockerExecutionBroker._has_link_component(path)
            or hashlib.sha256(path.read_bytes()).hexdigest() != item['program_sha256']):
        raise ContractError('feasibility original diagnostic program differs')
    return replay


def feasibility_public_material(cell, task, scenario, body, calls):
    row = body.get('feasibility_replay')
    if not isinstance(row, dict): raise ContractError('missing feasibility native replay')
    from research_loop.modular.modules.improvement import CandidatePackage
    rebuilt = derive_feasibility_replay(cell=cell, task=task, scenario=scenario,
        package=CandidatePackage(R(row['package'])), events=[{'stage': 'objective_lock', 'data': row['lock']}, *row['timeline']])
    if (rebuilt.data() != row or row['final_candidate'] != calls.get('final')
            or row['stages'] != [r['data'] for r in body['mechanism_stages']]
            or row['request_digests'] != [r['request_digest'] for r in body['responses']]):
        raise ContractError('feasibility projection differs from the original native replay')
    originals = {e['data']['request_digest']: e['data']['request'] for e in row['timeline'] if e['stage'] == 'model_request'}
    replies = {e['data']['request_digest']: e['data']['response'] for e in row['timeline'] if e['stage'] == 'model_response'}
    if any(originals.get(r['request_digest']) != r['request'] or replies.get(r['request_digest']) != r['response'] for r in body['responses']):
        raise ContractError('feasibility projection changed an original request or response')
    return row['public_material']
