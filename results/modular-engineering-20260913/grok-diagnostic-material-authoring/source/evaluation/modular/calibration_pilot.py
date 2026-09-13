"""Diagnostic TRAIN calibration, intentionally incompatible with calibration eligibility.

All journal paths are private evaluator custody. Authority receipts authenticate
delegated ports, not the truth or physical independence of their observations.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from evaluation.modular.calibration import COVERAGE_KINDS
from evaluation.modular.reference_store import FrozenTrainReferenceResolver, _plain
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.ontology import ContractError, canonical, digest

PILOT_SCHEMA = 'four-train-diagnostic-calibration-v1'
OPPORTUNITIES = 72
ROLES = ('reviewer1', 'reviewer2', 'arbitrator', 'evaluator')
BENCHMARKS = ('blade', 'discoverybench')
DIMENSIONS = {'blade': ('cvars', 'transform', 'model'),
              'discoverybench': ('context', 'variable_f1', 'relation')}


def runtime_code_paths():
    root = Path(__file__).parent
    return {'pilot_code': root / 'calibration_pilot.py', 'worker_code': root / 'calibration_pilot_process.py',
            'rubric_code': root / 'scoring_service.py', 'resolver_code': root / 'reference_store.py'}


def runtime_code_pins():
    return {name: hashlib.sha256(_plain(path).read_bytes()).hexdigest() for name, path in runtime_code_paths().items()}


def exact(value, fields):
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise ContractError('diagnostic contract fields differ')
    return value


def pin(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ContractError('diagnostic digest is invalid')
    return value


def integer(value, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ContractError('diagnostic integer is invalid')
    return value


def dimensions(value, benchmark):
    exact(value, DIMENSIONS[benchmark])
    for name, number in value.items():
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 1:
            raise ContractError('diagnostic dimensions are invalid')
        if (benchmark == 'blade' or name == 'relation') and number not in (0, .5, 1):
            raise ContractError('diagnostic ordinal dimension is invalid')
        if name == 'context' and number not in (0, 1):
            raise ContractError('diagnostic context dimension is invalid')
    return dict(value)


def target(value, benchmark):
    exact(value, ('state', 'dimensions'))
    if value['state'] not in ('known', 'unknown', 'not_applicable'):
        raise ContractError('diagnostic target state is invalid')
    if value['state'] == 'known':
        dimensions(value['dimensions'], benchmark)
    elif value['dimensions'] is not None:
        raise ContractError('unknown diagnostic target cannot contain dimensions')
    return dict(value)


@dataclass(frozen=True)
class DiagnosticAuthority:
    authority_id: str
    key: bytes

    def __post_init__(self):
        if not isinstance(self.authority_id, str) or not self.authority_id or not isinstance(self.key, bytes) or len(self.key) < 32:
            raise ContractError('diagnostic authority is invalid')

    def issue(self, role: str, subject: str, payload: Mapping) -> FrozenRecord:
        body = {'schema': 'diagnostic-authority-receipt-v1', 'role': role,
                'authority': self.authority_id, 'subject': pin(subject),
                'payload': dict(payload), 'validation_eligible': False}
        return FrozenRecord.from_dict({'body': body, 'mac': hmac.new(self.key, canonical(body).encode(), hashlib.sha256).hexdigest()})


def verify(receipt, *, role, subject, authority_id, key):
    if not isinstance(receipt, FrozenRecord):
        raise ContractError('diagnostic receipt must be immutable')
    envelope = exact(receipt.data(), ('body', 'mac'))
    body = exact(envelope['body'], ('schema', 'role', 'authority', 'subject', 'payload', 'validation_eligible'))
    if (body['schema'] != 'diagnostic-authority-receipt-v1' or body['role'] != role
            or body['subject'] != subject or body['authority'] != authority_id
            or body['validation_eligible'] is not False or not isinstance(envelope['mac'], str)
            or not hmac.compare_digest(envelope['mac'], hmac.new(key, canonical(body).encode(), hashlib.sha256).hexdigest())):
        raise ContractError('diagnostic receipt binding is invalid')
    return body['payload']


def slot_id(identity_digest, kind):
    return digest({'identity_digest': pin(identity_digest), 'kind': kind})


def validate_grid(manifest: FrozenRecord, *, schema):
    if not isinstance(manifest, FrozenRecord):
        raise ContractError('pilot manifest must be immutable')
    body = exact(manifest.data(), ('schema', 'tasks', 'slots', 'policy', 'authorities', 'input_pins', 'validation_eligible'))
    if body['schema'] != schema or body['validation_eligible'] is not False:
        raise ContractError('pilot is diagnostic only')
    if not isinstance(body['tasks'], list) or len(body['tasks']) != 4:
        raise ContractError('pilot requires exactly four train identities')
    tasks = {}
    for row in body['tasks']:
        exact(row, ('identity', 'task_handle', 'task_digest', 'reference_digest'))
        identity = DataIdentity.parse(row['identity'])
        identity.require_train()
        if identity.benchmark not in BENCHMARKS:
            raise ContractError('pilot requires primary benchmarks')
        for field in ('task_handle', 'task_digest', 'reference_digest'):
            pin(row[field])
        key = digest(identity.data())
        if key in tasks:
            raise ContractError('pilot identity is duplicated')
        tasks[key] = row
    if any(sum(row['identity']['benchmark'] == bench for row in tasks.values()) != 2 for bench in BENCHMARKS):
        raise ContractError('pilot requires two tasks per benchmark')
    if len({row['task_handle'] for row in tasks.values()}) != 4:
        raise ContractError('pilot handles are duplicated')
    if not isinstance(body['slots'], list) or len(body['slots']) != 36:
        raise ContractError('pilot requires all thirty-six slots')
    expected = {slot_id(i, kind) for i in tasks for kind in COVERAGE_KINDS}
    slots = {}
    for row in body['slots']:
        exact(row, ('slot_id', 'identity_digest', 'kind', 'status', 'material_digest', 'candidate_digest'))
        if (row['identity_digest'] not in tasks or row['kind'] not in COVERAGE_KINDS
                or row['slot_id'] != slot_id(row['identity_digest'], row['kind']) or row['slot_id'] in slots
                or row['status'] not in ('ready', 'unresolved_material', 'not_applicable')):
            raise ContractError('pilot slot differs from frozen grid')
        pin(row['material_digest'])
        if row['status'] == 'ready':
            pin(row['candidate_digest'])
        elif row['candidate_digest'] is not None:
            raise ContractError('unavailable slot cannot have candidate')
        slots[row['slot_id']] = row
    if set(slots) != expected:
        raise ContractError('pilot grid is incomplete')
    authorities = exact(body['authorities'], ('material', 'reviewer1', 'reviewer2', 'arbitrator', 'capacity', 'diagnostic'))
    if any(not isinstance(v, str) or not v for v in authorities.values()) or len(set(authorities.values())) != len(authorities):
        raise ContractError('pilot authorities must be distinct')
    if not isinstance(body['input_pins'], Mapping) or not body['input_pins']:
        raise ContractError('pilot requires caller source pins')
    for value in body['input_pins'].values():
        pin(value)
    if any(body['input_pins'].get(name) != value for name, value in runtime_code_pins().items()):
        raise ContractError('pilot running implementation differs from frozen code pins')
    return body, tasks, slots


def validate_manifest(manifest: FrozenRecord):
    body, tasks, slots = validate_grid(manifest, schema=PILOT_SCHEMA)
    policy = exact(body['policy'], ('ports', 'max_calls', 'max_tokens', 'max_microusd'))
    exact(policy['ports'], ROLES)
    for name in ('max_calls', 'max_tokens', 'max_microusd'):
        integer(policy[name], minimum=1)
    if policy['max_calls'] > 180:
        raise ContractError('pilot global opportunities exceed fixed design')
    for role, spec in policy['ports'].items():
        exact(spec, ('model', 'parameters', 'context_digest', 'tokenizer_digest', 'pricing_digest',
                     'context_window', 'max_output_tokens', 'max_calls', 'max_tokens_per_call', 'max_microusd_per_call'))
        if not isinstance(spec['model'], str) or not spec['model'] or not isinstance(spec['parameters'], Mapping):
            raise ContractError('pilot model configuration must be explicit')
        for name in ('context_digest', 'tokenizer_digest', 'pricing_digest'):
            pin(spec[name])
        for name in ('context_window', 'max_output_tokens', 'max_calls', 'max_tokens_per_call', 'max_microusd_per_call'):
            integer(spec[name], minimum=1)
        if spec['max_calls'] > (72 if role == 'evaluator' else 36):
            raise ContractError('pilot role exceeds fixed opportunity bound')
        if spec['max_output_tokens'] >= spec['context_window']:
            raise ContractError('pilot context budget is invalid')
    return body, tasks, slots


class PrivateJournal:
    """Exclusive, fsynced hash chain. Reopening a run is intentionally unsupported."""
    def __init__(self, path: Path):
        self.path = _plain(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('x', encoding='utf-8'):
            pass
        self.sequence = 0
        self.previous = '0' * 64

    def append(self, event, data):
        row = {'sequence': self.sequence, 'previous': self.previous, 'event': event, 'data': data}
        row['digest'] = digest(row)
        with _plain(self.path).open('a', encoding='utf-8') as stream:
            stream.write(canonical(row) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        self.sequence += 1
        self.previous = row['digest']


@dataclass(frozen=True)
class PortResult:
    output: FrozenRecord
    cost: FrozenRecord


class PilotTransportError(Exception):
    def __init__(self, *, partial_response=None, reported_cost=None):
        super().__init__('diagnostic transport failed')
        self.partial_response = partial_response
        self.reported_cost = reported_cost


def raw_record(value):
    if isinstance(value, FrozenRecord):
        return value.data()
    if isinstance(value, Mapping):
        try:
            return FrozenRecord.from_dict(value).data()
        except (ValueError, TypeError, ContractError):
            pass
    return None


class PortBudget:
    def __init__(self, manifest, journal, *, capacity_port, capacity_key, source_guard=None):
        self.body, _, _ = validate_manifest(manifest)
        self.manifest = manifest
        self.journal = journal
        self.capacity_port = capacity_port
        self.capacity_key = capacity_key
        self.calls = {role: 0 for role in ROLES}
        self.costs = {role: 0 for role in ROLES}
        self.tokens = {role: 0 for role in ROLES}
        self.unknown = {role: 0 for role in ROLES}
        self.failed = {role: 0 for role in ROLES}
        self.invalid = {role: 0 for role in ROLES}
        self.halted = False
        self.halt_reason = None
        self.usage_receipts = set()
        self.capacity_checks = 0
        self.source_guard = source_guard

    def _guard(self, role, request):
        if self.source_guard is None:
            return True
        try:
            self.source_guard()
            return True
        except Exception:
            self.halted = True
            self.halt_reason = 'blocked_source_drift'
            self.journal.append('source_guard_rejected', {'role': role, 'request_digest': request.content_hash})
            return False

    def call(self, role, request, port):
        policy = self.body['policy']
        spec = policy['ports'][role]
        if self.halted:
            return None, self.halt_reason
        if sum(self.calls.values()) >= policy['max_calls'] or self.calls[role] >= spec['max_calls']:
            return None, 'budget_exhausted'
        quote_request = FrozenRecord.from_dict({'schema': 'diagnostic-capacity-request-v1', 'manifest_digest': self.manifest.content_hash,
            'role': role, 'request_digest': request.content_hash, 'port_config': spec, 'request': request.data()})
        # This port is caller-trusted deterministic measurement, never a model port.
        if not self._guard(role, request):
            return None, self.halt_reason
        try:
            self.capacity_checks += 1
            quote = self.capacity_port(quote_request)
            q = verify(quote, role='capacity', subject=quote_request.content_hash,
                       authority_id=self.body['authorities']['capacity'], key=self.capacity_key)
            exact(q, ('input_tokens_upper', 'output_tokens_upper', 'cost_microusd_upper', 'reliable', 'nonbillable_capacity_check'))
            if q['reliable'] is not True or q['nonbillable_capacity_check'] is not True:
                raise ContractError('capacity or cost is not reliable')
            for name in ('input_tokens_upper', 'output_tokens_upper', 'cost_microusd_upper'):
                integer(q[name])
            count = q['input_tokens_upper'] + q['output_tokens_upper']
            amount = q['cost_microusd_upper']
            if (q['output_tokens_upper'] != spec['max_output_tokens'] or count > spec['context_window']
                    or count > spec['max_tokens_per_call'] or amount > spec['max_microusd_per_call']
                    or sum(self.tokens.values()) + count > policy['max_tokens']
                    or sum(self.costs.values()) + amount > policy['max_microusd']):
                raise ContractError('capacity reservation exceeds frozen limit')
            if not self._guard(role, request):
                return None, self.halt_reason
        except Exception:
            self.journal.append('capacity_rejected', {'role': role, 'request_digest': request.content_hash})
            return None, 'capacity_rejected'
        self.journal.append('port_reserved', {'role': role, 'request_digest': request.content_hash,
            'quote': quote.data(), 'tokens_reserved': count, 'microusd_reserved': amount})
        self.calls[role] += 1
        self.tokens[role] += count
        self.costs[role] += amount
        output = raw_cost = None
        failed = False
        try:
            result = port(request)
            if not isinstance(result, PortResult):
                raise PilotTransportError()
            output, raw_cost = result.output, result.cost
        except Exception as exc:
            failed = True
            if isinstance(exc, PilotTransportError):
                output, raw_cost = exc.partial_response, exc.reported_cost
        self.journal.append('port_raw', {'role': role, 'request_digest': request.content_hash,
            'output': raw_record(output), 'reported_cost': raw_record(raw_cost), 'transport_failed': failed})
        try:
            cost = exact(raw_record(raw_cost), ('input_tokens', 'output_tokens', 'microusd',
                'request_digest', 'port_config_digest', 'usage_evidence_digest'))
            for name in ('input_tokens', 'output_tokens', 'microusd'):
                integer(cost[name])
            if cost['request_digest'] != request.content_hash or cost['port_config_digest'] != digest(spec):
                raise ContractError('reported usage has a foreign model or request binding')
            pin(cost['usage_evidence_digest'])
            if cost['usage_evidence_digest'] in self.usage_receipts:
                raise ContractError('one actual usage receipt cannot be charged as another call')
            self.usage_receipts.add(cost['usage_evidence_digest'])
            self.tokens[role] += cost['input_tokens'] + cost['output_tokens'] - count
            self.costs[role] += cost['microusd'] - amount
            cost_status = 'verified_reported'
            if (cost['input_tokens'] > q['input_tokens_upper'] or cost['output_tokens'] > q['output_tokens_upper']
                    or cost['microusd'] > amount):
                self.halted = True
                self.halt_reason = 'blocked_reservation_breach'
                cost_status = 'reported_reservation_breach'
        except (ContractError, TypeError, ValueError):
            self.unknown[role] += 1
            self.halted = True
            self.halt_reason = 'blocked_unknown_cost'
            cost_status = 'unknown_reservation_retained'
        if failed or not isinstance(output, FrozenRecord):
            self.failed[role] += 1
        self.journal.append('port_closed', {'role': role, 'request_digest': request.content_hash, 'cost_status': cost_status,
            'status': 'failed' if failed or not isinstance(output, FrozenRecord) else 'received'})
        if failed or not isinstance(output, FrozenRecord):
            return None, 'transport_failed'
        if cost_status != 'verified_reported':
            return None, 'unknown_cost'
        return output, 'received'

    def data(self):
        return {'calls': dict(self.calls), 'failed_calls': dict(self.failed), 'known_or_reserved_tokens': dict(self.tokens),
                'invalid_response_calls': dict(self.invalid), 'nonbillable_capacity_checks': self.capacity_checks,
                'known_or_reserved_microusd': dict(self.costs), 'unknown_cost_calls': dict(self.unknown),
                'further_io_blocked': self.halted, 'halt_reason': self.halt_reason}


def blind_request(manifest, slot, task, material):
    # Expected targets and other review outputs must never enter this request.
    return FrozenRecord.from_dict({'schema': 'diagnostic-blind-review-request-v1',
        'manifest_digest': manifest.content_hash, 'slot_id': slot['slot_id'],
        'benchmark': task['identity']['benchmark'], 'identity_digest': slot['identity_digest'],
        'task_handle': task['task_handle'], 'reference_digest': task['reference_digest'],
        'candidate_digest': slot['candidate_digest'], 'candidate': material['candidate']})


class DiagnosticPilot:
    manifest_validator = staticmethod(validate_manifest)
    budget_type = PortBudget
    observation_schema = 'four-train-diagnostic-observation-v1'

    def augment_report(self, report):
        return report

    def __init__(self, *, manifest, resolver: FrozenTrainReferenceResolver, materials: Mapping[str, FrozenRecord],
                 keys: Mapping[str, bytes], journal_path: Path, capacity_port: Callable,
                 reviewer1: Callable, reviewer2: Callable, arbitrator: Callable, evaluator: Callable,
                 authority: DiagnosticAuthority, source_guard):
        self.manifest = manifest
        self.body, self.tasks, self.slots = self.manifest_validator(manifest)
        if not callable(source_guard):
            raise ContractError('pilot requires a caller source verification guard')
        if not isinstance(resolver, FrozenTrainReferenceResolver):
            raise ContractError('pilot requires the standard train resolver')
        if (set(keys) != set(self.body['authorities']) or any(not isinstance(k, bytes) or len(k) < 32 for k in keys.values())
                or len(set(keys.values())) != len(keys) or authority.authority_id != self.body['authorities']['diagnostic']
                or authority.key != keys['diagnostic']):
            raise ContractError('pilot authority delegation is invalid')
        if set(materials) != set(self.slots):
            raise ContractError('pilot material inventory differs from all slots')
        parsed = {}
        for sid, slot in self.slots.items():
            receipt = materials[sid]
            if not isinstance(receipt, FrozenRecord) or receipt.content_hash != slot['material_digest']:
                raise ContractError('pilot material pin differs')
            material = verify(receipt, role='material', subject=sid,
                authority_id=self.body['authorities']['material'], key=keys['material'])
            exact(material, ('status', 'candidate', 'expected', 'support_digest'))
            pin(material['support_digest'])
            target(material['expected'], self.tasks[slot['identity_digest']]['identity']['benchmark'])
            if material['status'] != slot['status']:
                raise ContractError('pilot material status differs')
            if slot['status'] == 'ready':
                if not isinstance(material['candidate'], Mapping) or digest(material['candidate']) != slot['candidate_digest']:
                    raise ContractError('pilot candidate pin differs')
            elif material['candidate'] is not None or material['expected']['state'] == 'known':
                raise ContractError('unavailable material cannot claim known candidate')
            parsed[sid] = material
        # Validate all membership and material contracts before reading any reference.
        self.journal = PrivateJournal(journal_path)
        self.journal.append('pilot_reserved', {'manifest_digest': manifest.content_hash, 'slots': 36, 'evaluator_opportunities': 72})
        try:
            source_guard()
            for identity_digest, task in self.tasks.items():
                ref = resolver(task['task_handle'], task['identity']['benchmark'])
                if (ref.content_hash != task['reference_digest'] or ref.data()['identity_digest'] != identity_digest
                        or digest({'identity': task['identity'], 'payload': ref.data()['task_context']}) != task['task_digest']):
                    raise ContractError('pilot reference binding differs')
        except Exception:
            self.journal.append('pilot_source_rejected', {'status': 'failed_before_ports'})
            raise ContractError('pilot source preflight failed') from None
        self.journal.append('sources_verified', {'task_count': 4})
        self.materials, self.keys, self.resolver, self.authority = parsed, dict(keys), resolver, authority
        self.ports = {'reviewer1': reviewer1, 'reviewer2': reviewer2, 'arbitrator': arbitrator, 'evaluator': evaluator}
        self.budget = self.budget_type(manifest, self.journal, capacity_port=capacity_port, capacity_key=keys['capacity'], source_guard=source_guard)
        self.ran = False

    def _review(self, role, request, benchmark):
        output, status = self.budget.call(role, request, self.ports[role])
        if output is None:
            return None, status
        try:
            result = verify(output, role=role, subject=request.content_hash,
                authority_id=self.body['authorities'][role], key=self.keys[role])
            target(result, benchmark)
            return result, 'reviewed'
        except Exception:
            self.budget.invalid[role] += 1
            self.journal.append('review_rejected', {'role': role, 'request_digest': request.content_hash})
            return None, 'invalid_review'

    def run(self):
        if self.ran:
            raise ContractError('diagnostic run cannot be replayed')
        self.ran = True
        decisions = {}
        for sid in sorted(self.slots):
            slot = self.slots[sid]
            if slot['status'] != 'ready':
                decisions[sid] = {'state': slot['status'], 'target': None}
                continue
            task = self.tasks[slot['identity_digest']]
            benchmark = task['identity']['benchmark']
            request = blind_request(self.manifest, slot, task, self.materials[sid])
            first, status1 = self._review('reviewer1', request, benchmark)
            second, status2 = self._review('reviewer2', request, benchmark)
            if first is None or second is None:
                decisions[sid] = {'state': 'review_unresolved', 'target': None, 'review_statuses': [status1, status2]}
            elif first == second:
                decisions[sid] = {'state': 'reviewed', 'target': first}
            else:
                # Arbitration gets the same blind material, no judge or expected target.
                result, status = self._review('arbitrator', request, benchmark)
                decisions[sid] = {'state': 'arbitrated' if result is not None else 'review_unresolved',
                                  'target': result, 'arbitration_status': status}
        frozen_decisions = FrozenRecord.from_dict(decisions)
        self.journal.append('reviews_frozen', {'decisions': decisions, 'decisions_digest': frozen_decisions.content_hash})
        observations = []
        for sid in sorted(self.slots):
            slot = self.slots[sid]
            task = self.tasks[slot['identity_digest']]
            for repeat in range(2):
                obs = {'slot_id': sid, 'identity_digest': slot['identity_digest'], 'benchmark': task['identity']['benchmark'],
                       'repeat': repeat, 'status': 'not_attempted', 'dimensions': None}
                decision = decisions[sid]
                if decision['state'] in ('unresolved_material', 'not_applicable', 'review_unresolved'):
                    obs['status'] = decision['state']
                else:
                    model_status = []
                    def model(request):
                        output, status = self.budget.call('evaluator', request, self.ports['evaluator'])
                        model_status.append(status)
                        if output is None:
                            raise ContractError('diagnostic evaluator unavailable')
                        return output
                    endpoint = FrozenBenchmarkRubricEndpoint(resolver=self.resolver, evaluator=model,
                        evaluator_id='diagnostic:' + self.manifest.content_hash,
                        evaluator_version=self.body['policy']['ports']['evaluator']['context_digest'])
                    request = FrozenRecord.from_dict({'schema': 'adapted-rubric-evaluation-request-v1',
                        'panel_digest': self.manifest.content_hash, 'scorer_config_digest': digest(self.body['policy']['ports']['evaluator']),
                        'benchmark': task['identity']['benchmark'], 'task_handle': task['task_handle'],
                        'identity_digest': slot['identity_digest'], 'candidate': self.materials[sid]['candidate'],
                        'candidate_digest': slot['candidate_digest']})
                    try:
                        response = endpoint(request)
                        obs.update({'status': 'scored_diagnostic', 'dimensions': response.data()['dimensions'],
                                    'response_digest': response.content_hash})
                    except Exception:
                        if model_status and model_status[-1] == 'received':
                            self.budget.invalid['evaluator'] += 1
                        obs['status'] = (model_status[-1] if model_status and model_status[-1] != 'received'
                                         else 'invalid_evaluator_output' if model_status else 'source_rejected')
                observations.append(obs)
                self.journal.append('opportunity_closed', obs)
        report = summarize(self.body, decisions, observations)
        report['material_review_target_disagreements'] = sum(
            decision['target'] is not None and decision['target'] != self.materials[sid]['expected']
            for sid, decision in decisions.items())
        report.update({'schema': self.observation_schema, 'manifest_digest': self.manifest.content_hash,
                       'review_decisions_digest': frozen_decisions.content_hash, 'budget': self.budget.data(),
                       'validation_eligible': False, 'calibration_eligible': False,
                       'official_metric_equivalence': 'not_established', 'scientific_validity': 'not_measured'})
        result = self.authority.issue('diagnostic', self.manifest.content_hash, self.augment_report(report))
        self.journal.append('pilot_completed', {'receipt_digest': result.content_hash, 'evaluator_opportunities': 72})
        return result


def summarize(body, decisions, observations):
    stats = {}
    slots = {slot['slot_id']: slot for slot in body['slots']}
    for benchmark in BENCHMARKS:
        selected = [o for o in observations if o['benchmark'] == benchmark]
        counts = {}
        errors = {name: [] for name in DIMENSIONS[benchmark]}
        confusion = {name: {} for name in DIMENSIONS[benchmark] if name != 'variable_f1'}
        repeated = {name: [] for name in DIMENSIONS[benchmark]}
        for obs in selected:
            counts[obs['status']] = counts.get(obs['status'], 0) + 1
            expected = decisions[obs['slot_id']]['target']
            if obs['dimensions'] is not None and expected is not None and expected['state'] == 'known':
                for name, observed in obs['dimensions'].items():
                    truth = expected['dimensions'][name]
                    errors[name].append(abs(observed - truth))
                    if name in confusion:
                        key = f'{float(truth):g}:{float(observed):g}'
                        confusion[name][key] = confusion[name].get(key, 0) + 1
        for sid in {o['slot_id'] for o in selected}:
            pair = [o for o in selected if o['slot_id'] == sid and o['dimensions'] is not None]
            if len(pair) == 2:
                for name in repeated:
                    repeated[name].append(abs(pair[0]['dimensions'][name] - pair[1]['dimensions'][name]))
        stats[benchmark] = {'opportunities': len(selected), 'statuses': counts, 'source_tasks': 2,
            'observed_groups': len({t['identity']['group_id'] for t in body['tasks'] if t['identity']['benchmark'] == benchmark}),
            'dimension_confusion': confusion,
            'absolute_error': {name: {'n': len(values), 'mean': sum(values) / len(values) if values else None} for name, values in errors.items()},
            'repeat_absolute_difference': {name: {'pairs': len(values), 'mean': sum(values) / len(values) if values else None} for name, values in repeated.items()}}
    return {'source_task_count': 4, 'slot_count': 36, 'evaluator_opportunity_count': 72,
            'observed_group_count': len({task['identity']['group_id'] for task in body['tasks']}),
            'independent_sample_count_claimed': None, 'per_benchmark': stats,
            'observations': observations, 'coverage_slots': {kind: sum(s['kind'] == kind for s in slots.values()) for kind in COVERAGE_KINDS},
            'review_states': {sid: decisions[sid]['state'] for sid in sorted(decisions)}}
