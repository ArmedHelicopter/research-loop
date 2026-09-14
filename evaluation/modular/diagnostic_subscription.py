"""Explicit included-subscription diagnostic budget; never an HTTP tariff adapter.

All material bodies, references, native streams and authority keys remain in the
private worker. The public ledger preserves incomplete accounting as unknown.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

from evaluation.modular.calibration_pilot import (
    DiagnosticAuthority, DiagnosticPilot, DIMENSIONS, PrivateJournal, ROLES,
    blind_request, exact, integer, pin, target, validate_grid, verify,
)
from evaluation.modular.calibration_pilot_process import load_record
from evaluation.modular.diagnostic_private_ports import PrivateRequestRenderer, context_digest
from evaluation.modular.reference_store import FrozenTrainReferenceResolver, _plain, _read_bound
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import (
    AcpResult, EXECUTABLE_SHA256, MODEL, DIAGNOSTIC_OPPORTUNITY_CONTRACT,
    diagnostic_config, known_usage, run_native_diagnostic,
)
from research_loop.ontology import ContractError, canonical, digest

import research_loop.modular.grok_native_deployment as native_deployment_module
from research_loop.modular.grok_native_deployment import (
    FrozenNativeDeployment, checked_deployment, diagnostic_receipt_schema)

SCHEMA = 'four-train-diagnostic-included-subscription-v1'
OBSERVATION_SCHEMA = 'four-train-diagnostic-subscription-observation-v1'
CONFIG_SCHEMA = 'diagnostic-subscription-worker-config-v1'
CONFIG_SCHEMA_V2 = 'diagnostic-subscription-worker-config-v2'
OBSERVATION_SCHEMA_V2 = 'four-train-diagnostic-subscription-observation-v2'
LIMITS = {'reviewer1': 36, 'reviewer2': 36, 'arbitrator': 36, 'evaluator': 72}


def record(value):
    return FrozenRecord.from_dict(value)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def own_sources():
    import research_loop.modular.grok_acp_transport as acp
    import evaluation.modular.diagnostic_private_ports as renderer
    import research_loop.modular.model_port as schemas
    import research_loop.modular.contracts as contracts
    import research_loop.ontology as ontology
    return {'subscription_code': Path(__file__), 'native_acp_code': Path(acp.__file__),
            'native_deployment_code': Path(native_deployment_module.__file__),
            'private_renderer_code': Path(renderer.__file__), 'schema_validator_code': Path(schemas.__file__),
            'frozen_contracts_code': Path(contracts.__file__), 'ontology_code': Path(ontology.__file__)}


def policy(*, input_byte_cap, main_output_cap, observed_main_token_cap, main_opportunities=180):
    """Construct explicit request bounds, not tokenization or monetary quotes."""
    return {'accounting': 'included_subscription_main_plus_possible_title_v1',
        'max_main_opportunities': main_opportunities,
        'max_title_opportunities': main_opportunities,
        'max_total_opportunities': 2 * main_opportunities,
        'ports': {role: {'model': MODEL, 'context_digest': context_digest(role),
            'max_calls': bound, 'max_input_bytes': input_byte_cap,
            'main_output_cap': main_output_cap, 'title_output_cap': 100, 'max_retries': 0,
            'timeout_seconds': 60, 'observed_main_token_cap': observed_main_token_cap}
            for role, bound in LIMITS.items()}}


def validate_manifest(manifest):
    b, tasks, slots = validate_grid(manifest, schema=SCHEMA)
    for name, path in own_sources().items():
        if b['input_pins'].get(name) != sha(path):
            raise ContractError('subscription implementation is not pinned')
    p = exact(b['policy'], ('accounting', 'ports', 'max_main_opportunities',
                           'max_title_opportunities', 'max_total_opportunities'))
    if p['accounting'] != 'included_subscription_main_plus_possible_title_v1':
        raise ContractError('subscription accounting contract differs')
    for name in ('max_main_opportunities', 'max_title_opportunities', 'max_total_opportunities'):
        integer(p[name], minimum=1)
    if (p['max_main_opportunities'] > 180 or p['max_title_opportunities'] != p['max_main_opportunities']
            or p['max_total_opportunities'] != 2 * p['max_main_opportunities']):
        raise ContractError('subscription opportunities exceed explicit design')
    exact(p['ports'], ROLES)
    for role, spec in p['ports'].items():
        exact(spec, ('model', 'context_digest', 'max_calls', 'max_input_bytes',
            'main_output_cap', 'title_output_cap', 'max_retries', 'timeout_seconds', 'observed_main_token_cap'))
        if (spec['model'] != MODEL or spec['context_digest'] != context_digest(role)
                or type(spec['title_output_cap']) is not int or spec['title_output_cap'] != 100
                or type(spec['max_retries']) is not int or spec['max_retries'] != 0
                or type(spec['timeout_seconds']) is not int or spec['timeout_seconds'] != 60):
            raise ContractError('subscription native bounds differ')
        integer(spec['max_calls'], minimum=1); integer(spec['max_input_bytes'], minimum=1)
        integer(spec['main_output_cap'], minimum=1)
        integer(spec['observed_main_token_cap'], minimum=spec['main_output_cap'] + 1)
        if spec['max_calls'] > LIMITS[role]:
            raise ContractError('subscription role opportunities exceed design')
    return b, tasks, slots


class SubscriptionRenderer(PrivateRequestRenderer):
    """Exact original request/reference logic, with explicit new manifest admission."""
    manifest_validator = staticmethod(validate_manifest)


def response_schema(role, request):
    if role == 'evaluator':
        return request.data()['output_schema']
    benchmark = request.data()['benchmark']
    return {'type': 'object', 'properties': {
        'state': {'type': 'string', 'enum': ['known', 'unknown', 'not_applicable']},
        'dimensions': {'type': ['object', 'null'], 'properties': {
            name: {'type': 'number', 'minimum': 0, 'maximum': 1}
            for name in DIMENSIONS[benchmark]}, 'required': list(DIMENSIONS[benchmark]),
            'additionalProperties': False}}, 'required': ['state', 'dimensions'],
        'additionalProperties': False}


def request_wire(renderer, role, request):
    # Preserve both exact renderer messages and their roles inside one ACP text.
    # No reference/candidate shortening or expected targets are introduced.
    return canonical(renderer.render(role, request).data())


def request_inventory(manifest, materials, renderer):
    """Compile every candidate/review/evaluator mapping before any model I/O."""
    _, tasks, slots = validate_manifest(manifest)
    entries = []
    for sid in sorted(slots):
        slot = slots[sid]
        if slot['status'] != 'ready':
            continue
        task = tasks[slot['identity_digest']]
        candidate = materials[sid]['candidate']
        review = blind_request(manifest, slot, task, materials[sid])
        requests = [(role, 0, review) for role in ROLES if role != 'evaluator']
        captured = []
        def capture(request):
            captured.append(request)
            raise ContractError('local request compilation only')
        endpoint = FrozenBenchmarkRubricEndpoint(resolver=renderer.resolver, evaluator=capture,
            evaluator_id='diagnostic:' + manifest.content_hash,
            evaluator_version=renderer.body['policy']['ports']['evaluator']['context_digest'])
        try:
            endpoint(record({'schema': 'adapted-rubric-evaluation-request-v1',
                'panel_digest': manifest.content_hash,
                'scorer_config_digest': digest(renderer.body['policy']['ports']['evaluator']),
                'benchmark': task['identity']['benchmark'], 'task_handle': task['task_handle'],
                'identity_digest': slot['identity_digest'], 'candidate': candidate,
                'candidate_digest': slot['candidate_digest']}))
        except ContractError:
            if len(captured) != 1:
                raise ContractError('standard evaluator request compilation failed') from None
        requests.extend(('evaluator', repeat, captured[0]) for repeat in range(2))
        for role, repeat, request in requests:
            wire = request_wire(renderer, role, request)
            size = len(wire.encode('utf-8'))
            if size > renderer.body['policy']['ports'][role]['max_input_bytes']:
                raise ContractError('complete private reference exceeds frozen byte cap')
            entries.append({'opportunity_id': digest({'slot_id': sid, 'role': role, 'repeat': repeat}),
                'slot_id': sid, 'role': role, 'repeat': repeat, 'request_digest': request.content_hash,
                'prompt_sha256': hashlib.sha256(wire.encode()).hexdigest(), 'input_bytes': size,
                'schema_digest': digest(response_schema(role, request)),
                'port_digest': digest(renderer.body['policy']['ports'][role])})
    return record({'schema': 'subscription-private-request-inventory-v1',
        'manifest_digest': manifest.content_hash, 'slot_count': 36,
        'review_opportunity_count': 108, 'evaluator_opportunity_count': 72, 'entries': entries})


@dataclass(frozen=True)
class SubscriptionResult:
    output: FrozenRecord | None
    native: FrozenRecord
    binding: FrozenRecord
    deployment: FrozenNativeDeployment | None = None


class SubscriptionBudget:
    """Reservation remains spent on failure; unknown main blocks later I/O."""
    def __init__(self, manifest, journal, *, capacity_port, capacity_key, source_guard):
        self.body, _, _ = validate_manifest(manifest)
        self.manifest, self.journal, self.plan = manifest, journal, capacity_port
        self.source_guard = source_guard
        self.calls = {r: 0 for r in ROLES}
        self.invalid = {r: 0 for r in ROLES}
        self.records = []
        self.halted = False; self.halt_reason = None
        self.session_ids = set(); self.prompt_ids = set(); self.opportunities = set()

    @staticmethod
    def included_snapshot(snapshot):
        return (isinstance(snapshot, dict) and snapshot.get('route') == 'grok_com_unified_subscription'
            and snapshot.get('auto_topup_rule_present') is False
            and all(type(snapshot.get(k)) is int and snapshot[k] == 0
                    for k in ('on_demand_cap', 'on_demand_used', 'prepaid_balance')))

    def halt(self, reason):
        self.halted = True; self.halt_reason = reason

    def call(self, role, request, port):
        if self.halted:
            return None, self.halt_reason
        p = self.body['policy']; spec = p['ports'][role]
        if sum(self.calls.values()) >= p['max_main_opportunities'] or self.calls[role] >= spec['max_calls']:
            return None, 'budget_exhausted'
        try:
            self.source_guard()
            bound = self.plan(role, request)
            b = bound.data()
            if b['opportunity_id'] in self.opportunities:
                raise ContractError('opportunity was already reserved')
            self.source_guard()
        except Exception:
            self.halt('blocked_preflight')
            self.journal.append('subscription_preflight_rejected', {'role': role, 'request_digest': request.content_hash})
            return None, self.halt_reason
        self.opportunities.add(b['opportunity_id']); self.calls[role] += 1
        self.journal.append('subscription_reserved', {'role': role, 'request_digest': request.content_hash,
            'binding': b, 'main_opportunities': 1, 'possible_title_opportunities': 1})
        result = None
        row = {'role': role, 'binding': b, 'known_main_usage': None, 'known_response_usage': [],
            'title_usage': None, 'title_cost_usd': None, 'all_opportunity_tokens': None,
            'all_opportunity_cost_usd': None, 'settled_additional_charge_usd': None,
            'status': 'unknown_main', 'native_receipt_digest': None}
        try:
            result = port(request)
            if not isinstance(result, SubscriptionResult) or result.binding != bound:
                raise ContractError('native provider binding differs')
            r = result.native.data()
            row.update(native_receipt_digest=result.native.content_hash,
                known_main_usage=known_usage(r.get('known_usage')),
                known_response_usage=r.get('known_response_usage', []),
                native_accepted=r.get('accepted'), native_faults=r.get('faults'),
                main_binding_verified=r.get('known_usage_binding_verified'),
                main_dispatch_state='possibly_dispatched' if r.get('prompt_may_have_been_dispatched') is True
                    else 'not_dispatched' if r.get('prompt_may_have_been_dispatched') is False else 'unknown',
                native_prompt_reservations=r.get('prompt_requests_reserved'),
                title_opportunity_may_have_occurred=r.get('prompt_may_have_been_dispatched'),
                reported_main_cost_usd=r.get('reported_cost_usd'))
            self.journal.append('subscription_native_receipt', {'role': role, 'receipt': r, 'binding': b})
            if result.deployment is not None:
                if (r.get('native_deployment') != checked_deployment(result.deployment).record.data()
                        or r.get('deployment_digest') != result.deployment.digest):
                    raise ContractError('subscription deployment receipt differs')
            usage = row['known_main_usage']
            if (r.get('schema') != diagnostic_receipt_schema(result.deployment) or r.get('accepted') is not True
                    or r.get('faults') != [] or r.get('known_usage_binding_verified') is not True
                    or not usage or usage['usageIsIncomplete'] or usage['modelCalls'] != 1
                    or usage['numTurns'] != 1 or usage['outputTokens'] > spec['main_output_cap']
                    or usage['totalTokens'] > spec['observed_main_token_cap']
                    or r.get('requested_model') != MODEL or r.get('requested_max_retries') != 0
                    or r.get('requested_max_completion_tokens') != spec['main_output_cap']
                    or r.get('opportunity_contract') != DIAGNOSTIC_OPPORTUNITY_CONTRACT
                    or r.get('requested_initial_title_output_cap') != 100
                    or r.get('requested_initial_title_model') != MODEL
                    or r.get('max_main_prompt_opportunities') != 1
                    or r.get('max_initial_title_opportunities') != 1
                    or not r.get('runtime_empty_inventory_count')
                    or not self.included_snapshot(r.get('billing_before'))
                    or not self.included_snapshot(r.get('billing_after'))
                    or not isinstance(result.output, FrozenRecord)):
                raise ContractError('native main accounting or gate rejected')
            if r['session_id'] in self.session_ids or r['prompt_id'] in self.prompt_ids:
                raise ContractError('native identity replay')
            self.session_ids.add(r['session_id']); self.prompt_ids.add(r['prompt_id'])
            self.source_guard()
            row['status'] = 'known_main_expected_unknown_title'
        except Exception:
            self.halt('blocked_native_or_source_fault')
            if row['known_main_usage'] is not None:
                row['status'] = 'rejected_with_known_usage_preserved'
            elif row.get('main_dispatch_state') == 'not_dispatched':
                row['status'] = 'rejected_before_prompt_dispatch'
        self.records.append(row)
        self.journal.append('subscription_closed', row)
        return (result.output, 'received') if not self.halted else (None, self.halt_reason)

    def data(self):
        return {'schema': 'included-subscription-diagnostic-budget-v1', 'calls': dict(self.calls),
            'invalid_response_calls': dict(self.invalid),
            'reserved_main_opportunities': sum(self.calls.values()),
            'reserved_possible_title_opportunities': sum(self.calls.values()),
            'unused_main_opportunities': self.body['policy']['max_main_opportunities'] - sum(self.calls.values()),
            'unused_possible_title_opportunities': self.body['policy']['max_title_opportunities'] - sum(self.calls.values()),
            'role_opportunities': {r: {'design': LIMITS[r], 'reserved': self.calls[r],
                'unused': LIMITS[r] - self.calls[r]} for r in ROLES},
            'records': list(self.records), 'all_opportunity_tokens': None,
            'all_opportunity_cost_usd': None, 'settled_additional_charge_usd': None,
            'further_io_blocked': self.halted, 'halt_reason': self.halt_reason}


class SubscriptionPilot(DiagnosticPilot):
    manifest_validator = staticmethod(validate_manifest)
    budget_type = SubscriptionBudget
    observation_schema = OBSERVATION_SCHEMA

    def augment_report(self, report):
        return report | {'material_availability': {state: sum(s['status'] == state for s in self.slots.values())
            for state in ('ready', 'unresolved_material', 'not_applicable')},
            'material_expected_states': {state: sum(m['expected']['state'] == state for m in self.materials.values())
            for state in ('known', 'unknown', 'not_applicable')}}


def verify_native_request_binding(result, entry, directory, spec, frozen_files, *, deployment=None):
    """Bind returned objects to actual private native receipt/reservation bytes."""
    r = result.receipt.data()
    if record(json.loads((directory / 'native' / 'observer-receipt.json').read_bytes())) != result.receipt:
        raise ContractError('returned native receipt differs from private record')
    if result.response is None:
        raise ContractError('native response is absent')
    expected = {'prompt_sha256': entry['prompt_sha256'], 'schema_sha256': entry['schema_digest'],
        'response_sha256': result.response.content_hash,
        'reservation_sha256': sha(directory / 'native-reservation.json'),
        'source_manifest_sha256': digest(frozen_files),
        'input_byte_cap': spec['max_input_bytes'], 'observed_main_token_cap': spec['observed_main_token_cap']}
    if deployment is not None:
        checked_deployment(deployment)
        expected['deployment_digest'] = deployment.digest
        if r.get('native_deployment') != deployment.record.data() or r.get('deployment_digest') != deployment.digest:
            raise ContractError('native deployment receipt binding differs')
    if r.get('schema') != diagnostic_receipt_schema(deployment) or r.get('diagnostic_binding') != expected:
        raise ContractError('native response/request/source binding differs')
    reservation = json.loads((directory / 'native-reservation.json').read_bytes())
    if deployment is not None and (reservation.get('schema') != 'grok-acp-single-prompt-reservation-v2'
            or reservation.get('deployment_digest') != deployment.digest):
        raise ContractError('native deployment reservation differs')
    if (reservation.get('prompt_sha256') != entry['prompt_sha256']
            or reservation.get('schema_sha256') != entry['schema_digest']
            or reservation.get('source_manifest_sha256') != digest(frozen_files)
            or reservation.get('session_id') != r.get('session_id')
            or reservation.get('prompt_id') != r.get('prompt_id')
            or reservation.get('model') != MODEL
            or r.get('source_manifest_sha256') != digest(frozen_files)):
        raise ContractError('native reservation binding differs')


class PrivateSubscriptionPorts:
    def __init__(self, *, manifest, resolver, authorities, inventory, native_slots,
                 frozen_files, executable, root, source_guard, fixture_factory=None, deployment=None):
        self.deployment = None if deployment is None else checked_deployment(deployment)
        diagnostic_receipt_schema(self.deployment)
        self.renderer = SubscriptionRenderer(manifest, resolver)
        self.manifest, self.authorities, self.inventory = manifest, authorities, inventory
        self.root = _plain(Path(root)); self.root.mkdir(parents=True, exist_ok=False)
        self.native_slots, self.frozen_files = native_slots, frozen_files
        self.executable, self.guard, self.fixture_factory = executable, source_guard, fixture_factory
        self.pending = {}; self.used = set(); self.halted = False

    def plan(self, role, request):
        if self.halted:
            raise ContractError('subscription provider is terminal')
        self.guard()
        wire = request_wire(self.renderer, role, request)
        schema = response_schema(role, request)
        entries = [e for e in self.inventory.data()['entries'] if e['role'] == role
            and e['request_digest'] == request.content_hash and e['opportunity_id'] not in self.used]
        if not entries:
            raise ContractError('request is not in unused frozen inventory')
        entry = entries[0]
        if (entry['prompt_sha256'] != hashlib.sha256(wire.encode()).hexdigest()
                or entry['schema_digest'] != digest(schema)
                or entry['input_bytes'] != len(wire.encode())
                or entry['port_digest'] != digest(self.renderer.body['policy']['ports'][role])):
            raise ContractError('private request changed after freeze')
        self.pending[(role, request.content_hash)] = (entry, wire, schema)
        return record(entry)

    def call(self, role, request):
        if self.halted:
            raise ContractError('subscription provider is terminal')
        try:
            self.guard()
            entry, wire, schema = self.pending.pop((role, request.content_hash))
            if entry['opportunity_id'] in self.used:
                raise ContractError('subscription opportunity reuse')
            self.used.add(entry['opportunity_id'])
            directory = self.root / entry['opportunity_id']
            directory.mkdir(exist_ok=False)
            spec = self.renderer.body['policy']['ports'][role]
            if self.fixture_factory is not None:
                result = self.fixture_factory(entry, wire, schema, directory, self.frozen_files,
                    spec)
            else:
                slot = self.native_slots[entry['opportunity_id']]
                result = run_native_diagnostic(opportunity_contract=DIAGNOSTIC_OPPORTUNITY_CONTRACT,
                    executable=self.executable, cwd=slot['cwd'], private_home=slot['private_home'],
                    private_profile=slot['private_profile'], private_dir=directory / 'native',
                    reservation=directory / 'native-reservation.json', frozen_files=self.frozen_files,
                    prompt=wire, schema=schema, main_output_cap=spec['main_output_cap'],
                    observed_main_token_cap=spec['observed_main_token_cap'], input_byte_cap=spec['max_input_bytes'],
                    **({} if self.deployment is None else {'deployment': self.deployment}))
            if not isinstance(result, AcpResult):
                raise ContractError('native result type differs')
            if not result.receipt.data().get('accepted'):
                self.halted = True
            output = result.response
            try:
                verify_native_request_binding(result, entry, directory, spec, self.frozen_files, deployment=self.deployment)
            except Exception:
                self.halted = True
                output = None  # Native usage survives even a coherent response swap.
            if output is not None and role != 'evaluator':
                try:
                    target(output.data(), request.data()['benchmark'])
                    output = self.authorities[role].issue(role, request.content_hash, output.data())
                except Exception:
                    self.halted = True
                    output = None  # Preserve native receipt even when review semantics fail.
            return SubscriptionResult(output, result.receipt, record(entry), self.deployment)
        except Exception:
            self.halted = True
            raise ContractError('private subscription provider failed') from None

    def kwargs(self):
        return {r: (lambda request, role=r: self.call(role, request)) for r in ROLES} | {'capacity_port': self.plan}


def load_private(config_descriptor):
    c = exact(load_record(config_descriptor).data(), ('schema', 'manifest', 'materials', 'key_files',
        'reference_store', 'input_files', 'journal_path', 'request_inventory', 'native_deployment'))
    if c['schema'] not in (CONFIG_SCHEMA, CONFIG_SCHEMA_V2):
        raise ContractError('subscription worker schema differs')
    manifest = load_record(c['manifest']); b, _, _ = validate_manifest(manifest)
    if set(c['input_files']) != set(b['input_pins']):
        raise ContractError('subscription source inventory differs')
    def guard():
        load_record(config_descriptor)
        for name, path in c['input_files'].items():
            if not Path(path).is_absolute():
                raise ContractError('subscription input path must be absolute')
            _read_bound(Path(path), {b['input_pins'][name]})
        for desc in (c['manifest'], c['materials'], *c['key_files'].values()):
            exact(desc, ('path', 'sha256'))
            if not Path(desc['path']).is_absolute():
                raise ContractError('subscription private custody path must be absolute')
            _read_bound(Path(desc['path']), {pin(desc['sha256'])})
    guard()
    exact(c['key_files'], b['authorities'])
    keys = {role: _read_bound(Path(desc['path']), {pin(desc['sha256'])})[0]
            for role, desc in c['key_files'].items()}
    authorities = {r: DiagnosticAuthority(b['authorities'][r], key) for r, key in keys.items()}
    store = exact(c['reference_store'], ('root', 'manifest_sha256', 'inventory_digest', 'split_digest'))
    if not Path(store['root']).is_absolute() or not Path(c['journal_path']).is_absolute():
        raise ContractError('subscription store and journal must be absolute')
    resolver = FrozenTrainReferenceResolver(Path(store['root']), manifest_sha256=store['manifest_sha256'],
        inventory_digest=store['inventory_digest'], split_digest=store['split_digest'])
    materials = {sid: record(row) for sid, row in load_record(c['materials']).data().items()}
    return c, manifest, materials, authorities, resolver, guard


def compile_inventory(config_descriptor, output):
    c, manifest, materials, authorities, resolver, guard = load_private(config_descriptor)
    # Constructing the pilot verifies every signed expected target/material and
    # every reference before compiling any request. No model port can execute.
    def forbidden(*args):
        raise ContractError('compile phase has no model transport')
    pilot = SubscriptionPilot(manifest=manifest, resolver=resolver, materials=materials,
        keys={r: a.key for r, a in authorities.items()}, authority=authorities['diagnostic'],
        journal_path=Path(str(output) + '.preflight.jsonl'), source_guard=guard,
        capacity_port=forbidden, **{r: forbidden for r in ROLES})
    inventory = request_inventory(manifest, pilot.materials, SubscriptionRenderer(manifest, resolver))
    guard()
    with _plain(Path(output)).open('x', encoding='utf-8') as f:
        f.write(inventory.encoded); f.flush(); os.fsync(f.fileno())
    return {'path': str(Path(output).absolute()), 'sha256': sha(output)}


def run_private(config_descriptor, *, fixture_factory=None):
    c, manifest, materials, authorities, resolver, guard = load_private(config_descriptor)
    inventory = load_record(c['request_inventory'])
    def full_guard():
        guard(); load_record(c['request_inventory'])
        if c['native_deployment'] is not None:
            load_record(c['native_deployment'])
    native_descriptor = None
    if fixture_factory is None:
        deployment = load_record(c['native_deployment']).data()
        versioned = deployment.get('schema') == 'frozen-native-subscription-deployment-v2'
        if versioned != (c['schema'] == CONFIG_SCHEMA_V2):
            raise ContractError('subscription worker/deployment version binding differs')
        exact(deployment, ('schema', 'executable', 'frozen_files', 'slots', *(['native'] if versioned else [])))
        if not versioned and deployment['schema'] != 'frozen-native-subscription-deployment-v1':
            raise ContractError('native deployment schema differs')
        if versioned:
            native_descriptor = FrozenNativeDeployment(record(deployment['native']))
            diagnostic_receipt_schema(native_descriptor)
        executable = deployment['executable']
        if native_descriptor is not None:
            native_descriptor.verify_executable(executable)
        elif not Path(executable).is_absolute() or sha(executable) != EXECUTABLE_SHA256:
            raise ContractError('native executable differs')
        frozen = dict(deployment['frozen_files']); slots = deployment['slots']
        if native_descriptor is not None:
            frozen[c['native_deployment']['path']] = c['native_deployment']['sha256']
            frozen[config_descriptor['path']] = config_descriptor['sha256']
        if not isinstance(frozen, dict) or any(not Path(p).is_absolute() for p in frozen):
            raise ContractError('native frozen source paths must be absolute')
        expected = {e['opportunity_id'] for e in inventory.data()['entries']}
        if set(slots) != expected:
            raise ContractError('all native request profiles must be frozen before execution')
        required = {str(Path(path)): manifest.data()['input_pins'][name] for name, path in c['input_files'].items()}
        required[executable] = EXECUTABLE_SHA256 if native_descriptor is None else native_descriptor.record.data()['executable_sha256']
        if native_descriptor is not None:
            required.update(native_descriptor.source_pins())
            required[c['native_deployment']['path']] = c['native_deployment']['sha256']
        homes = []
        roles = {e['opportunity_id']: e['role'] for e in inventory.data()['entries']}
        for opportunity_id, slot in slots.items():
            exact(slot, ('cwd', 'private_home', 'private_profile'))
            for path in slot.values():
                if not Path(path).is_absolute():
                    raise ContractError('native profile path must be absolute')
                homes.append(str(Path(path).resolve()))
            config = Path(slot['private_home']) / 'config.toml'
            if config.read_text(encoding='utf-8') != diagnostic_config(manifest.data()['policy']['ports'][roles[opportunity_id]]['main_output_cap']):
                raise ContractError('native config differs')
            required[str(config)] = sha(config)
        if len(homes) != len(set(homes)) or any(frozen.get(k) != v for k, v in required.items()):
            raise ContractError('native profiles reused or source pins omitted')
        original_guard = full_guard
        def full_guard():
            original_guard()
            for path, expected_hash in frozen.items():
                _read_bound(Path(path), {pin(expected_hash)})
    else:
        if c['schema'] == CONFIG_SCHEMA_V2:
            raise ContractError('versioned subscription requires the native deployment entry')
        executable = None; slots = {}; frozen = {str(p): sha(p) for p in own_sources().values()}
    ports = PrivateSubscriptionPorts(manifest=manifest, resolver=resolver, authorities=authorities,
        inventory=inventory, native_slots=slots, frozen_files=frozen, executable=executable,
        root=Path(c['journal_path'] + '.acp'), source_guard=full_guard, fixture_factory=fixture_factory,
        deployment=native_descriptor)
    pilot = SubscriptionPilot(manifest=manifest, resolver=resolver, materials=materials,
        keys={r: a.key for r, a in authorities.items()}, authority=authorities['diagnostic'],
        journal_path=Path(c['journal_path']), source_guard=full_guard, **ports.kwargs())
    if request_inventory(manifest, pilot.materials, ports.renderer) != inventory:
        raise ContractError('all private request mappings must match the frozen inventory')
    result = pilot.run()
    report = verify(result, role='diagnostic', subject=manifest.content_hash,
        authority_id=authorities['diagnostic'].authority_id, key=authorities['diagnostic'].key)
    try:
        full_guard()
        report['postrun_sources_verified'] = True
    except Exception:
        pilot.budget.halt('blocked_postrun_source_drift')
        report['postrun_sources_verified'] = False
        report['budget'] = pilot.budget.data()
        pilot.journal.append('subscription_postrun_source_rejected', {'further_io_blocked': True})
    if native_descriptor is not None:
        report.update(schema=OBSERVATION_SCHEMA_V2, native_deployment_digest=native_descriptor.digest,
            native_deployment_descriptor=dict(c['native_deployment']), worker_config_descriptor=dict(config_descriptor))
    result = authorities['diagnostic'].issue('diagnostic', manifest.content_hash, report)
    pilot.journal.append('subscription_result_finalized', {'receipt_digest': result.content_hash})
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('freeze', 'run'))
    parser.add_argument('--config', required=True); parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        desc = {'path': args.config, 'sha256': args.sha256}
        if args.action == 'freeze':
            result = compile_inventory(desc, args.output)
            print(json.dumps({'status': 'frozen', 'sha256': result['sha256']}))
        else:
            output = _plain(Path(args.output))
            if output.exists():
                raise ContractError('subscription result already exists')
            result = run_private(desc)
            with output.open('x', encoding='utf-8') as f:
                f.write(result.encoded); f.flush(); os.fsync(f.fileno())
            print(json.dumps({'status': 'completed', 'receipt_sha256': sha(output)}))
        return 0
    except Exception:
        print('{"status":"failed","receipt_sha256":null}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
