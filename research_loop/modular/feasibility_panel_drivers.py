"""Train-only Q5.1/Q5.2 drivers with real bounded Docker receipts.

Authority verifier ports are configured outside this module.  A verified
signature and source binding establish provenance only; they do not establish
scientific correctness or calibration.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Protocol

from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionReceipt
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text, strict_bool
from research_loop.modular.modules.exploration import ExplorationPlan, FeasibilityObservation, ResourceClosure, assess_feasibility
from research_loop.modular.modules.predictions import PredictionRegistry, _prediction
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.ontology import ContractError


_Q51 = ("subjective", "data", "minimal_run", "measurement", "independent")
_Q52 = ("zero_exit_same_prediction", "negative_control")
_STAGES = ("data", "minimal_run", "discriminating_measurement", "independent_result")


class FeasibilityAuthorityPort(Protocol):
    """Caller-owned signature verifier; it must not return an unsigned dict."""
    def verify_stage(self, subject: FrozenRecord) -> FrozenRecord: ...
    def verify_prediction_outcome(self, subject: FrozenRecord) -> FrozenRecord: ...


class PublicInputResolver(Protocol):
    def __call__(self, task: PublicTask, bundle: FrozenRecord) -> Mapping[str, Path]: ...


def _map(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a mapping")
    return value


def _hex(value: Any, name: str) -> str:
    value = required_text(value, name)
    if len(value) != 64 or any(item not in "0123456789abcdef" for item in value):
        raise ContractError(f"{name} must be a sha256 digest")
    return value


def _inputs(value: Any) -> dict[str, dict[str, Any]]:
    rows = _map(value, "public CSV artifact declarations")
    if not rows:
        raise ContractError("at least one public CSV artifact is required")
    result = {}
    for artifact_id, row in rows.items():
        row = dict(_map(row, "public CSV artifact"))
        if set(row) != {"sha256", "byte_count"} or type(row["byte_count"]) is not int or row["byte_count"] < 0:
            raise ContractError("public CSV artifact declaration is invalid")
        result[required_text(artifact_id, "artifact id")] = {"sha256": _hex(row["sha256"], "artifact sha256"),
                                                               "byte_count": row["byte_count"]}
    return result


def _closure(value: Any) -> dict[str, Any]:
    row = dict(_map(value, "resource closure"))
    if set(row) != {"data_version", "minimum_artifact_digest", "negative_control_id", "execution_units", "token_units"}:
        raise ContractError("resource closure fields are incomplete")
    ResourceClosure(**row)
    if any(type(row[k]) is not int for k in ("execution_units", "token_units")) or row["execution_units"] != 1:
        raise ContractError("closure requires one execution and strict integer token units")
    _hex(row["minimum_artifact_digest"], "minimum artifact digest")
    return row


def _stage_contracts(value: Any, identity: DataIdentity) -> dict[str, Any]:
    rows = _map(value, "stage contracts")
    if set(rows) != set(_STAGES):
        raise ContractError("every stage needs a frozen authority contract")
    result = {}
    for stage, raw in rows.items():
        row = dict(_map(raw, "stage contract"))
        if set(row) != {"source_id", "contract_id", "authorities"} or row["source_id"] != identity.group_id:
            raise ContractError("stage contract source drift")
        required_text(row["contract_id"], "contract id")
        authorities = row["authorities"]
        if not isinstance(authorities, list) or len(authorities) != 2:
            raise ContractError("exactly two frozen authorities required")
        for authority in authorities:
            if not isinstance(authority, Mapping) or set(authority) != {"authority_id", "source_group"}:
                raise ContractError("authority needs its explicit observation source")
            for field in authority:
                required_text(authority[field], field)
        if len({x["authority_id"] for x in authorities}) != 2:
            raise ContractError("authority identities must differ")
        if stage == "independent_result" and (len({x["source_group"] for x in authorities}) != 2
                or identity.group_id in {x["source_group"] for x in authorities}):
            raise ContractError("independent stage requires two separate external observation sources")
        result[stage] = row
    return result


def _branches(value: Any, contract: Mapping[str, Any], identity: DataIdentity) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 2 <= len(value) <= 8:
        raise ContractError("prediction branches must contain two to eight alternatives")
    rows = []
    for raw in value:
        row = dict(_map(raw, "prediction branch"))
        if set(row) != {"hypothesis_id", "mechanism_key", "mechanism", "intervention", "elimination_condition", "predictions"}:
            raise ContractError("prediction branch fields are incomplete")
        for field in set(row) - {"predictions"}:
            required_text(row[field], field)
        if not isinstance(row["predictions"], list) or len(row["predictions"]) != 1:
            raise ContractError("this bounded panel requires one shared discriminator")
        parsed = _prediction(row["predictions"][0])
        if parsed.discriminator_id != contract["discriminator_id"] or parsed.observable != contract["observable"]:
            raise ContractError("prediction and measurement discriminator binding drift")
        row["predictions"] = [parsed.data()]
        rows.append(row)
    if len({x["hypothesis_id"] for x in rows}) != len(rows) or len({x["intervention"] for x in rows}) != 1:
        raise ContractError("alternatives need unique IDs and one shared intervention")
    if _identifiable(rows):
        PredictionRegistry(identity).freeze("caller-frozen public distinguishability", rows, budget_units=1)
    return rows


def _identifiable(branches) -> bool:
    return len({FrozenRecord.from_dict({k: v for k, v in branch["predictions"][0].items()
                if k != "prediction_id"}).content_hash for branch in branches}) > 1


def _item(value: Any, identity: DataIdentity, *, prediction: bool) -> dict[str, Any]:
    row = dict(_map(value, "feasibility material"))
    required = {"source_id", "program", "program_sha256", "image", "inputs", "closure", "stage_contracts", "measurement_contract", "verification_budget"}
    if prediction:
        required.add("branches")
    if set(row) != required or row["source_id"] != identity.group_id:
        raise ContractError("feasibility material has incomplete or unbound fields")
    program = required_text(row["program"], "bounded public program")
    if "\r" in program or hashlib.sha256(program.replace("\n", os.linesep).encode("utf-8")).hexdigest() != _hex(row["program_sha256"], "program sha256"):
        raise ContractError("program text and frozen byte hash differ")
    image = required_text(row["image"], "pinned execution image")
    from research_loop.modular.benchmarks.execution import ExecutionRequest
    ExecutionRequest(identity, image, Path("unresolved.py"), {"public": Path("unresolved.csv")})
    result = {"source_id": required_text(row["source_id"], "material source"), "program": program,
              "program_sha256": row["program_sha256"], "image": image, "inputs": _inputs(row["inputs"]),
              "closure": _closure(row["closure"]), "stage_contracts": _stage_contracts(row["stage_contracts"], identity),
              "measurement_contract": FrozenRecord.from_dict(dict(_map(row["measurement_contract"], "measurement contract"))).data()}
    contract = result["measurement_contract"]
    if set(contract) != {"source_id", "contract_id", "discriminator_id", "observable", "negative_control_id"}:
        raise ContractError("measurement contract must bind source, discriminator and negative control")
    if contract["source_id"] != identity.group_id or contract["negative_control_id"] != result["closure"]["negative_control_id"]:
        raise ContractError("measurement source or negative control drift")
    for field, val in contract.items():
        required_text(val, field)
    if result["closure"]["minimum_artifact_digest"] != row["program_sha256"]:
        raise ContractError("closure minimum artifact does not bind the literal program")
    expected_budget = {"stage_calls": 4, "prediction_calls": int(prediction),
                       "cost_accounting": "authority_reported_or_unknown"}
    budget = dict(_map(row["verification_budget"], "verification budget"))
    if budget != expected_budget or any(type(budget.get(k)) is not int for k in ("stage_calls", "prediction_calls")):
        raise ContractError("verification opportunity budget drift")
    result["verification_budget"] = budget
    if prediction:
        result["branches"] = _branches(row["branches"], contract, identity)
    return result


def freeze_feasibility_panel_bundle(task: PublicTask, *, q51: Mapping[str, Mapping[str, Any]],
                                    q52: Mapping[str, Mapping[str, Any]]) -> FrozenRecord:
    if not isinstance(task, PublicTask) or not isinstance(q51, Mapping) or not isinstance(q52, Mapping):
        raise ContractError("feasibility bundle needs public task material")
    task.identity.require_train()
    if set(q51) != set(_Q51) or set(q52) != set(_Q52):
        raise ContractError("feasibility bundle variant coverage mismatch")
    return FrozenRecord.from_dict({"schema": "feasibility-panel-bundle-v2", "identity": task.identity.data(),
        "payload_digest": task.payload.content_hash, "q51": {name: _item(item, task.identity, prediction=False) for name, item in q51.items()},
        "q52": {name: _item(item, task.identity, prediction=True) for name, item in q52.items()}})


def feasibility_panel_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    if experiment_id not in {"Q5.1", "Q5.2"}:
        raise ContractError("feasibility injection only covers Q5.1/Q5.2")
    public = PublicTask(DataIdentity.parse(task.data()["identity"]), FrozenRecord.from_dict(task.data()["payload"]))
    body = evidence.data()
    if body.get("schema") != "feasibility-panel-bundle-v2":
        raise ContractError("caller-frozen feasibility bundle is required")
    bundle = FrozenRecord.from_dict(body)
    remade = freeze_feasibility_panel_bundle(public, q51=body.get("q51", {}), q52=body.get("q52", {}))
    if bundle.content_hash != remade.content_hash:
        raise ContractError("feasibility bundle is not a closed canonical reconstruction")
    if variant not in body["q51" if experiment_id == "Q5.1" else "q52"]:
        raise ContractError("feasibility variant is not registered")
    return {"schema": "feasibility-panel-controller-v2", "bundle": bundle.data()}


def _material(task: PublicTask, scenario: FrozenRecord, experiment_id: str, variant: str) -> tuple[FrozenRecord, dict[str, Any]]:
    body = scenario.data()
    if set(body) != {"experiment_id", "variant", "controller_input", "base", "controls"} or body["experiment_id"] != experiment_id or body["variant"] != variant:
        raise ContractError("feasibility scenario binding drift")
    controller = _map(body["controller_input"], "feasibility controller")
    if set(controller) != {"schema", "bundle"} or controller["schema"] != "feasibility-panel-controller-v2":
        raise ContractError("feasibility controller fields are incomplete")
    bundle = FrozenRecord.from_dict(dict(_map(controller["bundle"], "feasibility bundle")))
    raw = bundle.data(); remade = freeze_feasibility_panel_bundle(task, q51=raw.get("q51", {}), q52=raw.get("q52", {}))
    base = _map(body["base"], "feasibility base")
    if (bundle.content_hash != remade.content_hash or set(base) != {"task", "evidence", "budget"}
            or base["task"] != task.content_hash or base["evidence"] != bundle.content_hash):
        raise ContractError("feasibility caller material does not bind this scenario task")
    key = "q51" if experiment_id == "Q5.1" else "q52"
    return bundle, raw[key][variant]



def _aggregate(statuses):
    return 'failed' if 'failed' in statuses else 'unknown' if 'unknown' in statuses else 'passed'


def _verified(receipt, subject: FrozenRecord, *, prediction: bool) -> dict[str, Any]:
    if not isinstance(receipt, FrozenRecord):
        raise ContractError('verifier must return a frozen verified receipt')
    row = receipt.data(); body = subject.data()
    required = {'schema', 'subject_digest', 'status', 'observations', 'cost'}
    if prediction:
        required.add('classifications')
    schema = 'verified-prediction-outcome-v2' if prediction else 'verified-feasibility-stage-v2'
    if set(row) != required or row['schema'] != schema or row['subject_digest'] != subject.content_hash:
        raise ContractError('verifier subject or schema mismatch')
    contract = body['authority_contract']
    observations = row['observations']
    if not isinstance(observations, list) or len(observations) != 2:
        raise ContractError('two independently bound observations required')
    expected = {item['authority_id']: item['source_group'] for item in contract['authorities']}
    seen = set(); digests = set()
    for observation in observations:
        if not isinstance(observation, Mapping) or set(observation) != {'authority_id', 'source_group', 'observation_digest', 'contract_id', 'subject_digest', 'status', 'signature_verified'}:
            raise ContractError('observation fields incomplete')
        aid = observation['authority_id']
        if not isinstance(aid, str) or aid not in expected or aid in seen:
            raise ContractError('observation authority is not the frozen authority pair')
        seen.add(aid)
        if (observation['source_group'] != expected[aid] or observation['subject_digest'] != subject.content_hash
                or observation['contract_id'] != contract['contract_id']):
            raise ContractError('observation source, contract or subject mismatch')
        if strict_bool(observation['signature_verified'], 'signature verified') is not True:
            raise ContractError('observation signature was not verified')
        if observation['status'] not in ('passed', 'failed', 'unknown'):
            raise ContractError('observation status is invalid')
        digests.add(_hex(observation['observation_digest'], 'observation digest'))
    if len(digests) != 2 or row['status'] != _aggregate([x['status'] for x in observations]):
        raise ContractError('observation aggregation or distinctness mismatch')
    cost = row['cost']
    if (not isinstance(cost, Mapping) or set(cost) != {'unit', 'units'} or cost['unit'] != 'verifier_units'
            or (cost['units'] is not None and (type(cost['units']) is not int or cost['units'] < 0))):
        raise ContractError('verifier cost must be measured nonnegative units or explicit unknown')
    if row['status'] == 'passed' and body['execution_status'] != 'succeeded' and (prediction or body['stage'] != 'data'):
        raise ContractError('failed execution cannot qualify measurement or a subsequent gate')
    if (not prediction and body['stage'] == 'discriminating_measurement' and body['prediction_plan'] is not None
            and not _identifiable(body['prediction_plan']['branches']) and row['status'] == 'passed'):
        raise ContractError('identical declared predictions cannot qualify discriminating measurement')
    if prediction:
        classifications = row['classifications']
        expected_ids = {x['hypothesis_id'] for x in body['prediction_plan']['branches']}
        if (not isinstance(classifications, Mapping) or set(classifications) != expected_ids
                or any(x not in ('consistent', 'failed', 'unknown') for x in classifications.values())):
            raise ContractError('prediction classifications do not bind every frozen alternative')
        if (row['status'] != 'passed' or body['measurement_status'] != 'passed'
                or not _identifiable(body['prediction_plan']['branches'])):
            if any(x != 'unknown' for x in classifications.values()) or row['status'] == 'passed':
                raise ContractError('unknown, failed or indistinguishable observations cannot classify alternatives')
    return row


class _VerificationLedger:
    """Reserve every external verification before I/O, including shadow controls."""
    def __init__(self, workflow, item):
        self.workflow = workflow
        self.limits = item['verification_budget']
        self.used = {'stage_calls': 0, 'prediction_calls': 0}
        self.errors = 0
        workflow.session._record('feasibility_verification_allocation', {'limits': self.limits})

    def call(self, port, subject, *, prediction=False):
        kind = 'prediction_calls' if prediction else 'stage_calls'
        if self.used[kind] >= self.limits[kind]:
            raise ContractError('verification allocation exhausted')
        self.used[kind] += 1
        call_id = sum(self.used.values())
        common = {'call_id': call_id, 'kind': kind, 'limits': self.limits, 'used': dict(self.used),
                  'subject': subject.data(), 'subject_digest': subject.content_hash}
        self.workflow.session._record('feasibility_verifier_request', {**common, 'cost': {'unit': 'verifier_units', 'units': None}})
        raw = None
        try:
            method = getattr(port, 'verify_prediction_outcome' if prediction else 'verify_stage')
            raw = method(subject)
            if isinstance(raw, FrozenRecord):
                self.workflow.session._record('feasibility_verifier_response', {**common, 'receipt': raw.data()})
            row = _verified(raw, subject, prediction=prediction)
            self.workflow.session._record('feasibility_verifier_result', {**common, 'status': row['status'],
                'receipt_digest': raw.content_hash, 'cost': row['cost']})
            return row, raw.content_hash
        except Exception as exc:
            self.errors += 1
            # Preserve returned cost as an untrusted report; unknown verified cost is not zero.
            self.workflow.session._record('feasibility_verifier_failure', {**common, 'error_type': type(exc).__name__,
                'cost': {'unit': 'verifier_units', 'units': None},
                'reported_cost': raw.data().get('cost') if isinstance(raw, FrozenRecord) else None})
            return None, None


def _execute(workflow, *, bundle, item, broker, resolver):
    inputs = resolver(workflow.session.task, bundle)
    if not isinstance(inputs, Mapping) or set(inputs) != set(item['inputs']):
        raise ContractError('public input resolver set mismatch')
    artifacts = broker.validate_inputs(workflow.session.task.identity, inputs)
    expected = {key: {'artifact_id': key, **value} for key, value in item['inputs'].items()}
    if {x.artifact_id: x.record.data() for x in artifacts} != expected:
        raise ContractError('actual public input bytes differ from frozen material')
    receipt = workflow.session.execute(item['program'], broker=broker, image=item['image'], inputs=inputs)
    if (receipt.identity != workflow.session.task.identity or receipt.artifact is None
            or receipt.artifact.identity != workflow.session.task.identity
            or receipt.artifact.sha256 != item['program_sha256']
            or receipt.record.data().get('input_artifacts') != expected):
        raise ContractError('actual execution artifact set differs from frozen literal bytes')
    return receipt, artifacts


def _execution_public(execution):
    row = execution.record.data()
    # Host paths, argv, image and container IDs stay in the controller journal.
    return {'binding': execution.content_hash, 'status': execution.status,
            'program_sha256': execution.artifact.sha256 if execution.artifact else None,
            'input_artifacts': row.get('input_artifacts', {}), 'exit_code': row.get('exit_code'),
            'stdout': row.get('stdout', '')}


def _stage_subject(workflow, bundle, item, *, stage, execution, artifacts):
    return FrozenRecord.from_dict({'schema': 'feasibility-stage-subject-v2',
        'prediction_plan': {'identity': workflow.session.task.identity.data(), 'question': 'caller-frozen public distinguishability',
            'branches': item['branches'], 'budget_units': 1} if 'branches' in item else None,
        'identity': workflow.session.task.identity.data(), 'task_digest': workflow.session.task.content_hash,
        'objective_digest': workflow.session.objective.content_hash,
        'bundle_digest': bundle.content_hash, 'source_id': item['source_id'], 'stage': stage,
        'authority_contract': item['stage_contracts'][stage], 'measurement_contract': item['measurement_contract'],
        'program_sha256': item['program_sha256'], 'input_artifacts': [x.record.data() for x in artifacts],
        'execution_digest': execution.content_hash, 'execution_status': execution.status,
        'execution_observation': _execution_public(execution)})


def _invoke(workflow, cell, model, slot, instruction, context):
    return workflow.invoke_model(slot, model, instruction=instruction, module_context=FrozenRecord.from_dict({
        'panel_cell': opaque_panel_cell_binding(cell), 'required_objective_digest': workflow.session.objective.content_hash,
        **context}))


def _subjective(workflow, cell, model, item, execution):
    response = _invoke(workflow, cell, model, 'subjective',
        'Assess only the public diagnostic material. Return feasibility and rationale; this is not scientific admission.',
        {'public_material': {'program_sha256': item['program_sha256'], 'inputs': item['inputs'],
            'measurement_contract': item['measurement_contract']}, 'execution': _execution_public(execution)})
    row = response.data()
    if set(row) != {'feasibility', 'rationale'} or row['feasibility'] not in ('feasible', 'infeasible', 'unknown'):
        raise ContractError('invalid subjective assessment')
    required_text(row['rationale'], 'subjective rationale')
    return response


def _decision(public):
    if public['execution']['status'] != 'succeeded' or public['prediction']['identifiable'] is False:
        return 'stop'
    statuses = [value['status'] for value in public['stages'].values() if value is not None]
    if 'failed' in statuses or public['prediction']['status'] == 'failed':
        return 'stop'
    if 'unknown' in statuses or 'blocked' in statuses or public['prediction']['status'] == 'unknown':
        return 'defer'
    if statuses or public['prediction']['status'] == 'passed':
        return 'continue'
    return {'feasible': 'continue', 'infeasible': 'stop', 'unknown': 'defer'}[public['subjective']['feasibility']]


def _finish(workflow, cell, model, public):
    expected = _decision(public)
    diagnostic = _invoke(workflow, cell, model, 'diagnostic',
        'Choose continue, stop or defer for this bounded diagnostic, using the public observation. '
        'Stop on failed execution, explicit indistinguishability or failed gate; defer on unknown/blocked; '
        'otherwise continue on passed observations, or use subjective feasible/infeasible/unknown when no observations are available. '
        'Return decision and rationale. This decision never admits scientific evidence.', {'observation': public})
    row = diagnostic.data()
    if set(row) != {'decision', 'rationale'} or row['decision'] != expected:
        raise ContractError('diagnostic response contradicts frozen decision rule')
    required_text(row['rationale'], 'diagnostic rationale')
    workflow._trace('feasibility_diagnostic_decision', 'executed', decision=expected,
        public_observation_digest=FrozenRecord.from_dict(public).content_hash, response_digest=diagnostic.content_hash)
    final = _invoke(workflow, cell, model, 'final',
        'Return the standard candidate with required_objective_digest, empty evidence_ids and programme_complete=false. '
        'Use outcome invalid for a stop diagnostic, otherwise unknown. Never convert diagnostic feasibility into scientific support.',
        {'observation': public, 'diagnostic': diagnostic.data()})
    row = final.data()
    if (set(row) != {'objective_digest', 'outcome', 'evidence_ids', 'conclusion', 'programme_complete'}
            or row['objective_digest'] != workflow.session.objective.content_hash or row['evidence_ids'] != []
            or row['programme_complete'] is not False or row['outcome'] != ('invalid' if expected == 'stop' else 'unknown')):
        raise ContractError('final candidate violates bounded diagnostic decision')
    required_text(row['conclusion'], 'candidate conclusion')
    return diagnostic, final


def _run(driver, workflow, *, cell, scenario, model):
    bundle, item = _material(workflow.session.task, scenario, driver.experiment_id, cell.variant)
    prediction = driver.experiment_id == 'Q5.2'
    # Validate port availability before any execution or model attempt.
    if not callable(getattr(driver.authority, 'verify_stage', None)) or (prediction and not callable(getattr(driver.authority, 'verify_prediction_outcome', None))):
        raise ContractError('both configured verification capabilities are required')
    ledger = _VerificationLedger(workflow, item)
    runtime_plan = None
    if prediction and 'M4' in workflow.enabled:
        if _identifiable(item['branches']):
            runtime_plan = workflow.predictions.freeze('caller-frozen public distinguishability', item['branches'], budget_units=1)
        else:
            # Perform the actual module operation, retaining its expected semantic rejection.
            try:
                workflow.predictions.freeze('caller-frozen public distinguishability', item['branches'], budget_units=1)
            except ContractError:
                workflow._trace('m4_prediction_rejected', 'rejected', reason='identical_declared_predictions')
            else:
                raise ContractError('same-prediction plan unexpectedly admitted')
    execution, artifacts = _execute(workflow, bundle=bundle, item=item, broker=driver.broker, resolver=driver.input_resolver)
    subjective = _subjective(workflow, cell, model, item, execution)
    observations = {}; rows = {}; bindings = {}
    for stage in _STAGES:
        subject = _stage_subject(workflow, bundle, item, stage=stage, execution=execution, artifacts=artifacts)
        row, binding = ledger.call(driver.authority, subject)
        rows[stage] = row; bindings[stage] = binding
        group = item['stage_contracts'][stage]['authorities'][0]['source_group'] if stage == 'independent_result' else None
        observations[stage] = FeasibilityObservation(stage, row['status'] if row else 'unknown', binding or subject.content_hash, group)
    prediction_row = None; prediction_binding = None
    if prediction:
        frozen_plan = FrozenRecord.from_dict({'identity': workflow.session.task.identity.data(),
            'question': 'caller-frozen public distinguishability', 'branches': item['branches'], 'budget_units': 1})
        subject_body = _stage_subject(workflow, bundle, item, stage='discriminating_measurement', execution=execution, artifacts=artifacts).data()
        subject_body.update({'schema': 'prediction-outcome-subject-v2', 'prediction_plan': frozen_plan.data(),
            'prediction_plan_digest': frozen_plan.content_hash, 'discriminator_id': item['measurement_contract']['discriminator_id'],
            'measurement_receipt_digest': bindings['discriminating_measurement'],
            'measurement_status': observations['discriminating_measurement'].status})
        prediction_row, prediction_binding = ledger.call(driver.authority, FrozenRecord.from_dict(subject_body), prediction=True)
        if runtime_plan is not None and prediction_row is not None:
            update = workflow.predictions.record_outcome(runtime_plan.plan_id, item['measurement_contract']['discriminator_id'],
                prediction_binding, prediction_row['classifications'],
                {'trusted_evaluator': '+'.join(x['authority_id'] for x in prediction_row['observations']), 'verified': True})
            workflow._trace('prediction_outcome_bound', 'executed', runtime_plan_id=runtime_plan.plan_id,
                caller_plan_digest=frozen_plan.content_hash, verification_subject_digest=FrozenRecord.from_dict(subject_body).content_hash,
                outcome_digest=prediction_binding, update=update.data())
    if ledger.errors:
        raise ContractError('one or more verification attempts failed their frozen contract')
    report = assess_feasibility(ExplorationPlan('feasibility-' + bundle.content_hash, workflow.session.task.identity,
        bundle, ResourceClosure(**item['closure'])), observations)
    public = {'schema': 'public-feasibility-observation-v2', 'execution': _execution_public(execution),
        'subjective': subjective.data(),
        'stages': {stage: {'status': report.stages[stage], 'binding': bindings[stage]} if 'M7' in workflow.enabled else None for stage in _STAGES},
        'prediction': {'identifiable': _identifiable(item['branches']) if prediction and 'M4' in workflow.enabled else None,
            'status': prediction_row['status'] if prediction and 'M4' in workflow.enabled else None,
            'classifications': prediction_row['classifications'] if prediction and 'M4' in workflow.enabled else None,
            'binding': prediction_binding if prediction and 'M4' in workflow.enabled else None}}
    detail = {'stages': dict(report.stages), 'next_stage': report.next_stage, 'verification_used': ledger.used,
        'runtime_plan_digest': runtime_plan.payload.content_hash if runtime_plan else None,
        'public_observation': public, 'module_decision': _decision(public)}
    stage = workflow._trace('stage_3' if 'M7' in workflow.enabled else 'operation_m7_control', 'executed', **detail)
    diagnostic, final = _finish(workflow, cell, model, public)
    return stage, final, (subjective, diagnostic, final)


@dataclass(frozen=True)
class Q51FeasibilityDriver:
    broker: DockerExecutionBroker
    input_resolver: PublicInputResolver
    authority: FeasibilityAuthorityPort
    experiment_id: str = 'Q5.1'
    slots: tuple[str, ...] = ('subjective', 'diagnostic', 'final')
    execution_limit: int = 1
    docker_execution: str = 'one_matched_public_docker_execution'
    def slots_for(self, cell): return self.slots
    def run(self, workflow, *, cell, scenario, model, package):
        return _run(self, workflow, cell=cell, scenario=scenario, model=model)


@dataclass(frozen=True)
class Q52DistinguishabilityDriver(Q51FeasibilityDriver):
    experiment_id: str = 'Q5.2'


def install_drivers(target: MutableMapping[str, Any], *, broker: DockerExecutionBroker,
                    input_resolver: PublicInputResolver, authority: FeasibilityAuthorityPort):
    target.update({'Q5.1': Q51FeasibilityDriver(broker, input_resolver, authority),
                   'Q5.2': Q52DistinguishabilityDriver(broker, input_resolver, authority)})
    return target
