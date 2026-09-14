"""Frozen public lineage material and two configured provenance authorities.

Source qualification admits records to this train ledger only. Neither a MAC
nor different source-group names establishes scientific independence.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable

from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.combination_scoring import _signed_body
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.panel_receipts import _failed_solve_public_inputs
from research_loop.modular.train_controller import _write
from research_loop.modular.material_qualification_artifacts import MaterialQualificationArtifacts
from research_loop.ontology import ContractError


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value.encode('utf-8')) <= 16000


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _bindings(value):
    return isinstance(value, dict) and bool(value) and all(_text(k) and _text(v) for k, v in value.items())


@dataclass(frozen=True)
class FrozenLineageMaterial:
    record: FrozenRecord

    def __post_init__(self):
        if not isinstance(self.record, FrozenRecord) or len(self.record.encoded.encode('utf-8')) > 262144:
            raise ContractError('bounded frozen lineage material required')
        b = self.record.data()
        if (set(b) != {'schema', 'identity', 'task_digest', 'public_artifacts', 'question', 'originals',
                       'representations', 'claims', 'withdrawals', 'ordinary_summary', 'context_budget_bytes'}
                or b['schema'] != 'lineage-combination-material-v1' or not _digest(b['task_digest'])
                or not _text(b['question']) or not _text(b['ordinary_summary'])
                or type(b['context_budget_bytes']) is not int or not 1024 <= b['context_budget_bytes'] <= 65536
                or _failed_solve_public_inputs(b['public_artifacts']) is None):
            raise ContractError('lineage material fields or budget invalid')
        DataIdentity.parse(b['identity']).require_train()
        for name in ('originals', 'representations', 'claims', 'withdrawals'):
            if not isinstance(b[name], list) or len(b[name]) > 32:
                raise ContractError('lineage material needs bounded lists')
        if not b['originals'] or not b['claims']:
            raise ContractError('original observations and claims are required')
        roots, keys = set(), set()
        for row in b['originals']:
            if (not isinstance(row, dict) or set(row) != {'key', 'root_material', 'content', 'subject_bindings'}
                    or not _text(row['key']) or row['key'] in keys or not isinstance(row['root_material'], dict)
                    or not row['root_material'] or not isinstance(row['content'], dict) or not _bindings(row['subject_bindings'])):
                raise ContractError('original observation is malformed')
            roots.add(row['key']); keys.add(row['key'])
        for row in b['representations']:
            if (not isinstance(row, dict) or set(row) != {'key', 'root', 'representation', 'content'}
                    or not _text(row['key']) or row['key'] in keys or not isinstance(row['root'], str)
                    or row['root'] not in roots or row['representation'] not in {'report', 'summary'}
                    or not isinstance(row['content'], dict)):
                raise ContractError('derivative observation lacks its original root')
            keys.add(row['key'])
        claims = set()
        for row in b['claims']:
            if (not isinstance(row, dict) or set(row) != {'key', 'statement', 'subject_bindings', 'supports', 'refutes', 'depends_on'}
                    or not _text(row['key']) or row['key'] in claims or not _text(row['statement'])
                    or not _bindings(row['subject_bindings'])):
                raise ContractError('claim material malformed')
            for field, allowed in (('supports', roots), ('refutes', roots), ('depends_on', claims)):
                values = row[field]
                if (not isinstance(values, list) or any(not isinstance(v, str) for v in values)
                        or len(set(values)) != len(values) or not set(values) <= allowed):
                    raise ContractError('claim relation must bind roots and earlier DAG claims')
            if set(row['supports']) & set(row['refutes']):
                raise ContractError('one root cannot both support and refute a claim')
            claims.add(row['key'])
        withdrawn = set()
        for row in b['withdrawals']:
            if (not isinstance(row, dict) or set(row) != {'root', 'reason'} or not isinstance(row['root'], str)
                    or row['root'] not in roots or row['root'] in withdrawn or not _text(row['reason'])):
                raise ContractError('withdrawal must bind one original root')
            withdrawn.add(row['root'])
        forbidden = {'arm_id', 'enabled', 'control', 'truth', 'authority', 'path', 'argv', 'validation', 'gold'}
        def public(value):
            if isinstance(value, dict):
                return not forbidden.intersection(value) and all(public(v) for v in value.values())
            return all(public(v) for v in value) if isinstance(value, list) else True
        if not public({k: b[k] for k in ('originals', 'representations', 'claims')}):
            raise ContractError('public material contains controller or private fields')

    def data(self):
        return self.record.data()


def check_material_inputs(material, task, broker, public_inputs):
    if not isinstance(material, FrozenLineageMaterial) or not isinstance(broker, DockerExecutionBroker):
        raise ContractError('typed material and broker required')
    b = material.data()
    if b['identity'] != task.identity.data() or b['task_digest'] != task.content_hash:
        raise ContractError('material belongs to a different prepared task')
    actual = {a.artifact_id: a.record.data() for a in broker.validate_inputs(task.identity, public_inputs)}
    if FrozenRecord.from_dict(actual) != FrozenRecord.from_dict(_failed_solve_public_inputs(b['public_artifacts'])):
        raise ContractError('actual public input bytes differ from the frozen complete input set')


@dataclass(frozen=True)
class MaterialAuthority:
    authority: LinkedExecutionAuthority
    source_group: str
    verify: Callable[[FrozenRecord], FrozenRecord]


@dataclass(frozen=True)
class DualMaterialVerifier:
    authorities: tuple[MaterialAuthority, MaterialAuthority]
    cost_limit_per_call: int = 1

    def __post_init__(self):
        if (not isinstance(self.authorities, tuple) or len(self.authorities) != 2
                or any(not isinstance(a, MaterialAuthority) or not isinstance(a.authority, LinkedExecutionAuthority)
                       or not _text(a.source_group) or not callable(a.verify) for a in self.authorities)
                or len({a.authority.authority_id for a in self.authorities}) != 2
                or len({a.authority.key for a in self.authorities}) != 2
                or len({a.source_group for a in self.authorities}) != 2
                or type(self.cost_limit_per_call) is not int or self.cost_limit_per_call < 1):
            raise ContractError('two distinct configured material authorities and bounded calls required')

    def binding(self):
        return FrozenRecord.from_dict({'authorities': [{'authority': a.authority.authority_id,
            'source_group': a.source_group, 'key_digest': hashlib.sha256(a.authority.key).hexdigest()}
            for a in self.authorities], 'cost_limit_per_call': self.cost_limit_per_call})

    def request(self, material, cell_binding):
        if (not isinstance(cell_binding, FrozenRecord) or set(cell_binding.data()) != {'cell_digest', 'scenario_digest'}
                or any(not _digest(v) for v in cell_binding.data().values())):
            raise ContractError('source verification must bind its exact frozen cell and scenario')
        return FrozenRecord.from_dict({'schema': 'lineage-material-provenance-request-v1',
            'material': material.data(), 'material_digest': material.record.content_hash,
            'cell_binding': cell_binding.data(),
            'limits': {'calls': 1, 'cost_units': self.cost_limit_per_call}})

    def qualify(self, material, path, *, cell_binding):
        path = Path(path)
        request = self.request(material, cell_binding)
        DataIdentity.parse(request.data()['material']['identity']).require_train()
        if DockerExecutionBroker._has_link_component(path):
            raise ContractError('material provenance storage path is unsafe')
        if path.exists():
            raise ContractError('material verification opportunities already used')
        artifacts = None
        rejected = False
        try:
            path.parent.mkdir(parents=True, exist_ok=False)
            artifacts = MaterialQualificationArtifacts(path, request=request, binding=self.binding(),
                material=material.record, cell_binding=cell_binding)
            rows = []
            for number, a in enumerate(self.authorities):
                row = {'authority': a.authority.authority_id, 'request_digest': request.content_hash,
                       'limits': request.data()['limits'], 'status': 'reserved', 'response': None,
                       'cost_units': None, 'cost_unknown': True}
                rows.append(row)
                self._write_qualification(path, request, rows)
                artifacts.snapshot('reserved-' + str(number))
                artifacts.reserve(a.authority.authority_id, request)
                response = error = None
                try:
                    response = a.verify(request)
                except Exception as exc:
                    error = exc
                if error is None:
                    # Custody failure halts work; it is not an authority verdict.
                    artifacts.returned(a.authority.authority_id, response)
                    try:
                        if type(response) is not FrozenRecord:
                            raise ContractError('material authority response must be an exact frozen record')
                        row['response'] = response.data()
                        b = self._response(a, request, response)
                        row.update(status=b['verdict'], cost_units=b['cost_units'], cost_unknown=b['cost_units'] is None)
                    except Exception as exc:
                        error = exc
                if error is not None:
                    row.update(status='failed', error_type=type(error).__name__)
                artifacts.checked(a.authority.authority_id, row['status'],
                    response if type(response) is FrozenRecord else None, row['cost_units'], error)
                self._write_qualification(path, request, rows)
                artifacts.snapshot('checked-' + str(number))
            try:
                # Includes Admission's subject/agreement policy before sealing.
                self._verify_receipt(material, path, cell_binding=cell_binding)
            except Exception as qualification_error:
                try:
                    artifacts.terminal('rejected')
                except Exception as closure_error:
                    qualification_error.add_note('material rejection storage incomplete: ' + type(closure_error).__name__)
                    raise qualification_error from closure_error
                rejected = True
                raise
            artifacts.terminal('accepted')
        except Exception as exc:
            if artifacts is not None and not rejected:
                try:
                    artifacts.abort(exc)
                except Exception as storage_error:
                    exc.add_note('material failure storage incomplete: ' + type(storage_error).__name__)
            # Original failure remains the cause; public host receipts get only
            # this stable category, never a callback or filesystem error text.
            raise ContractError('material qualification failed; retained evidence is non-accepted') from exc
        return self.replay(material, path, cell_binding=cell_binding)

    def _write_qualification(self, path, request, rows):
        if DockerExecutionBroker._has_link_component(path):
            raise ContractError('material provenance storage path is unsafe')
        _write(path, {'request': request.data(), 'binding': self.binding().data(), 'calls': rows})

    def _response(self, authority, request, response):
        b = _signed_body(response, {authority.authority.authority_id: authority.authority.key}, message='material provenance')
        if (set(b) != {'schema', 'authority', 'request_digest', 'material_digest', 'identity', 'source_group', 'verdict', 'cost_units'}
                or b['schema'] != 'lineage-material-provenance-response-v1' or b['request_digest'] != request.content_hash
                or b['material_digest'] != request.data()['material_digest'] or b['identity'] != request.data()['material']['identity']
                or b['source_group'] != authority.source_group or b['verdict'] not in {'verified', 'rejected', 'unknown'}
                or b['cost_units'] is not None and (type(b['cost_units']) is not int or not 0 <= b['cost_units'] <= self.cost_limit_per_call)):
            raise ContractError('material authority failed exact subject or cost contract')
        return b

    def replay(self, material, path, *, cell_binding):
        request = self.request(material, cell_binding)
        MaterialQualificationArtifacts.verify(path, request=request, binding=self.binding(),
            material=material.record, cell_binding=cell_binding)
        return self._verify_receipt(material, path, cell_binding=cell_binding)

    def _verify_receipt(self, material, path, *, cell_binding):
        if DockerExecutionBroker._has_link_component(path) or not path.is_file():
            raise ContractError('material provenance must be an existing regular sidecar')
        import json
        b = json.loads(path.read_text(encoding='utf-8')); request = self.request(material, cell_binding)
        if (set(b) != {'request', 'binding', 'calls'} or FrozenRecord.from_dict(b['request']) != request
                or FrozenRecord.from_dict(b['binding']) != self.binding() or not isinstance(b['calls'], list) or len(b['calls']) != 2):
            raise ContractError('material provenance sidecar binding drift')
        for a, row in zip(self.authorities, b['calls']):
            if (set(row) != {'authority', 'request_digest', 'limits', 'status', 'response', 'cost_units', 'cost_unknown'}
                    or row.get('status') != 'verified' or row.get('authority') != a.authority.authority_id
                    or row.get('request_digest') != request.content_hash
                    or FrozenRecord.from_dict(row['limits']) != FrozenRecord.from_dict(request.data()['limits'])):
                raise ContractError('both configured material observations must qualify')
            response = self._response(a, request, FrozenRecord.from_dict(row['response']))
            if (response['verdict'] != 'verified' or type(row.get('cost_units')) is not type(response['cost_units'])
                    or row.get('cost_units') != response['cost_units']
                    or row.get('cost_unknown') is not (response['cost_units'] is None)):
                raise ContractError('material provenance accounting drift')
        return hashlib.sha256(path.read_bytes()).hexdigest()
