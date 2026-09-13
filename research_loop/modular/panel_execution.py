"""Shared public diagnostic boundary for independent experiment drivers.

Owns input declarations, restricted execution and model-visible observations;
it has no experiment selection, scientific admission or authority policy.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping, Protocol
from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.ontology import ContractError


class PublicInputResolver(Protocol):
    def __call__(self, task: PublicTask, bundle: FrozenRecord) -> Mapping[str, Path]: ...



def require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a mapping")
    return value



def require_sha256(value: Any, name: str) -> str:
    value = required_text(value, name)
    if len(value) != 64 or any(item not in "0123456789abcdef" for item in value):
        raise ContractError(f"{name} must be a sha256 digest")
    return value



def input_declarations(value: Any) -> dict[str, dict[str, Any]]:
    rows = require_mapping(value, "public CSV artifact declarations")
    if not rows:
        raise ContractError("at least one public CSV artifact is required")
    result = {}
    for artifact_id, row in rows.items():
        row = dict(require_mapping(row, "public CSV artifact"))
        if set(row) != {"sha256", "byte_count"} or type(row["byte_count"]) is not int or row["byte_count"] < 0:
            raise ContractError("public CSV artifact declaration is invalid")
        result[required_text(artifact_id, "artifact id")] = {"sha256": require_sha256(row["sha256"], "artifact sha256"),
                                                               "byte_count": row["byte_count"]}
    return result



def prepare_public_inputs(workflow, *, bundle, item, broker, resolver):
    inputs = resolver(workflow.session.task, bundle)
    if not isinstance(inputs, Mapping) or set(inputs) != set(item['inputs']):
        raise ContractError('public input resolver set mismatch')
    artifacts = broker.validate_inputs(workflow.session.task.identity, inputs)
    expected = {key: {'artifact_id': key, **value} for key, value in item['inputs'].items()}
    if {x.artifact_id: x.record.data() for x in artifacts} != expected:
        raise ContractError('actual public input bytes differ from frozen material')
    return inputs, artifacts



def execute_public_diagnostic(workflow, *, item, broker, prepared):
    inputs, artifacts = prepared
    expected = {key: {'artifact_id': key, **value} for key, value in item['inputs'].items()}
    receipt = workflow.session.execute(item['program'], broker=broker, image=item['image'], inputs=inputs)
    if (receipt.identity != workflow.session.task.identity or receipt.artifact is None
            or receipt.artifact.identity != workflow.session.task.identity
            or receipt.artifact.sha256 != item['program_sha256']
            or receipt.record.data().get('input_artifacts') != expected):
        raise ContractError('actual execution artifact set differs from frozen literal bytes')
    return receipt, artifacts



def public_execution_observation(execution):
    row = execution.record.data()
    # Host paths, argv, image and container IDs stay in the controller journal.
    return {'binding': execution.content_hash, 'status': execution.status,
            'program_sha256': execution.artifact.sha256 if execution.artifact else None,
            'input_artifacts': row.get('input_artifacts', {}), 'exit_code': row.get('exit_code'),
            'stdout': row.get('stdout', '')}



def invoke_panel_model(workflow, cell, model, slot, instruction, context):
    return workflow.invoke_model(slot, model, instruction=instruction, module_context=FrozenRecord.from_dict({
        'panel_cell': opaque_panel_cell_binding(cell), 'required_objective_digest': workflow.session.objective.content_hash,
        **context}))

