"""Custody -> restricted multi-job phase -> shared solver -> independent primary score.

This trusted train-only controller preserves every planned cell.  Execution
and scoring remain separate authorities; component signatures are not a claim
of independently deployed processes or scientific validity.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping

from evaluation.modular.custody import CustodyStore
from evaluation.modular.train_io import PublicTrainPacket
from research_loop.modular.combination_train_source import (
    CombinationTrainSource, source_schema_matches, source_item_matches, packet_index)
from evaluation.modular.combination_scoring import (
    CombinationAdaptedScoringService, verify_combination_adapted_receipt,
)
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.combination_panels import CombinationPanel, CombinationPanelVerifier
from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.exploration_scheduler_combination import (
    ExplorationSchedulerResult as CombinationBenchmarkCellResult, run_exploration_scheduler_cell,
    verify_exploration_scheduler_cell, FrozenExplorationSchedulerMaterial, issue_exploration_scheduler_score_input)
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.model_port import CodexModelPort, _validate_schema, _schema_witness
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell, PanelReceiptVerifier, ScientificScorerReceipt
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import _checked_roots, _reviewed_model_policy, _write
from research_loop.modular.train_provider_preflight import (native_envelope, native_source_fields,
    response_schemas, validate_native_declaration)
from research_loop.ontology import ContractError


SLOTS = ("analysis_program", "final_answer")
_PAIR = "pair:M7+M8"
_ANALYSIS = {"schema": "frozen-combination-contrast-analysis-v1", "direction": "higher_better",
             "value_range": [0.0, 1.0], "scale": "unit", "missing_policy": "incomplete_reject",
             "group_weighting": "task_replicate_mean_then_equal_group_mean"}


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _record(value: Any, field: str) -> FrozenRecord:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be a record")
    return FrozenRecord.from_dict(value)


def _names(value: Any) -> bool:
    return (isinstance(value, list) and bool(value) and all(isinstance(x, str) and x.strip() for x in value)
            and len(set(value)) == len(value))


def _design(baseline: str):
    design = default_compatibility(baseline).conditional_factorial(("M7", "M8"))
    arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in design.data()["cells"] if row["status"] == "executable"}
    if set(arms) != {"00", "10", "01", "11"} or design.data()["interaction_status"] != "identifiable":
        raise ContractError("registered compatibility does not admit the complete M7/M8 factorial")
    return design, arms


@dataclass(frozen=True)
class FrozenExplorationSchedulerTrainConfig:
    """Complete task, package, source, scorer and opportunity allocation."""
    record: FrozenRecord

    def __post_init__(self):
        if not isinstance(self.record, FrozenRecord):
            raise ContractError("combination controller configuration must be frozen")
        body = self.record.data()
        fields = {"schema", "domain", "stage", "item_ids", "task_bindings", "baseline_digest", "packages_by_arm",
                  "scorer", "scorer_handle_bindings", "acceptance_criteria", "replicates", "model", "effort",
                  "max_calls", "max_tokens", "schemas", "allocation", "image", "timeout_seconds", "materials_by_task"}
        native = native_envelope(body, 'exploration_scheduler')
        if not (source_schema_matches(body, fields, "exploration-scheduler-train-controller-config-v1")
                or native_source_fields(body, fields, family='exploration_scheduler')) or body["domain"] != "train":
            raise ContractError("controller supports the exact train-only M7/M8 configuration")
        if not isinstance(body["stage"], str) or not body["stage"].strip() or not _names(body["item_ids"]) or not _names(body["replicates"]):
            raise ContractError("stage, train allowlist and replicates must be nonempty and unique")
        if not _digest(body["baseline_digest"]):
            raise ContractError("combination baseline must be a digest")
        bindings = body["task_bindings"]
        if not isinstance(bindings, Mapping) or set(bindings) != set(body["item_ids"]):
            raise ContractError("task/source bindings must exactly cover the allowlist")
        identities = []
        for item_id, row in bindings.items():
            if (not isinstance(row, Mapping) or set(row) != {"identity", "task_digest", "csv_sha256", "csv_byte_count"}
                    or not _digest(row["task_digest"]) or not _digest(row["csv_sha256"])
                    or type(row["csv_byte_count"]) is not int or row["csv_byte_count"] < 1):
                raise ContractError("task/source binding is malformed")
            identity = DataIdentity.parse(row["identity"])
            identity.require_train()
            if not source_item_matches(body, item_id, identity):
                raise ContractError("allowlist and task identity differ")
            identities.append(identity)
        if len(identities) != 2 or len(body["replicates"]) != 1 or {i.benchmark for i in identities} != {"blade", "discoverybench"} or len({i.split_id for i in identities}) != 1:
            raise ContractError("controller requires both core benchmarks in one frozen train split")
        if len({r['task_digest'] for r in bindings.values()}) != 2:
            raise ContractError('duplicate task digest')
        materials = body['materials_by_task']
        if not isinstance(materials, dict) or set(materials) != {r['task_digest'] for r in bindings.values()}:
            raise ContractError('exact frozen per-task jobs required')
        for row in bindings.values():
            material = FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(materials[row['task_digest']]))
            if material.data()['identity'] != row['identity'] or material.data()['task_digest'] != row['task_digest'] or material.data()['public_artifacts'] != [{'artifact':{'artifact_id':'public_csv','sha256':row['csv_sha256'],'byte_count':row['csv_byte_count']},'container_path':'/input/public_csv'}]:
                raise ContractError('jobs must bind actual custody source')
        _, arms = _design(body["baseline_digest"])
        packages = body["packages_by_arm"]
        if not isinstance(packages, Mapping) or set(packages) != {a.content_hash for a in arms.values()}:
            raise ContractError("packages must exactly cover the registered four-arm grid")
        package_digests = set()
        for package in packages.values():
            candidate = CandidatePackage(_record(package, "package"))
            package_digests.add(candidate.digest)
            manifest = TrainingManifest(_record(candidate.record.data()["training_manifest"], "training manifest"))
            if set(manifest.identities()) != set(identities):
                raise ContractError("package training manifest differs from the exact train task set")
        if len(package_digests) != 1:
            raise ContractError("the four intervention arms must share the same frozen candidate package")
        scorer = _record(body["scorer"], "scorer")
        data = scorer.data()
        expected_scorer = ScorerConfig.create(benchmark="core_pair", evaluator_id=data.get("evaluator_id"),
            version=data.get("version"), rubric_digest=data.get("rubric_digest"))
        if expected_scorer.record != scorer:
            raise ContractError("controller requires one frozen core-pair scorer configuration")
        from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint
        if data['rubric_digest'] != FrozenBenchmarkRubricEndpoint.rubric_digest():
            raise ContractError('exact frozen primary rubric required')
        handles = body["scorer_handle_bindings"]
        identity_digests = {FrozenRecord.from_dict(i.data()).content_hash for i in identities}
        if not isinstance(handles, Mapping) or set(handles) != identity_digests or any(not _digest(v) for v in handles.values()):
            raise ContractError("scorer handles must exactly bind the frozen train identities")
        if _record(body["acceptance_criteria"], "criteria").data().get("contrast_analysis") != _ANALYSIS:
            raise ContractError("controller requires the existing frozen incomplete-reject contrast semantics")
        cells = len(identities) * len(body["replicates"]) * 4
        expected_allocation = {"model_slots_per_cell": list(SLOTS), "docker_attempts_per_cell": 3, "auxiliary_docker_attempts_per_cell": 2,
            "scorer_calls_per_cell": 1, "scorer_call_limit": cells, "scorer_token_accounting": "transport_not_provided"}
        if (not isinstance(body["allocation"], Mapping) or body["allocation"] != expected_allocation
                or any(type(body["allocation"].get(k)) is not int for k in
                       ("docker_attempts_per_cell", "auxiliary_docker_attempts_per_cell", "scorer_calls_per_cell", "scorer_call_limit"))):
            raise ContractError("model slots, Docker attempts and scorer opportunities must be equally frozen")
        if ((not native and (body["model"] != "gpt-5.6-luna" or body["effort"] != "low"
                or type(body["max_calls"]) is not int or body["max_calls"] != cells * len(SLOTS)
                or type(body["max_tokens"]) is not int or body["max_tokens"] < 1))
                or type(body["timeout_seconds"]) is not int or not 1 <= body["timeout_seconds"] <= 120):
            raise ContractError("model and exact full-panel budgets must be frozen")
        if (not isinstance(body["image"], str) or "@sha256:" not in body["image"]
                or not _digest(body["image"].rsplit("@sha256:", 1)[1])):
            raise ContractError("Docker image must be content pinned")
        schemas = response_schemas(body, family='exploration_scheduler')
        if not isinstance(schemas, Mapping) or set(schemas) != set(SLOTS):
            raise ContractError("exact two response schemas are required")
        for schema in schemas.values():
            if not isinstance(schema, Mapping) or schema.get("type") != "object":
                raise ContractError("response schemas must describe objects")
            _validate_schema(schema, _schema_witness(schema))
        if native:
            validate_native_declaration(body, family='exploration_scheduler', schemas=schemas,
                main_opportunities=cells*len(SLOTS))

    def data(self):
        return self.record.data()


@dataclass(frozen=True)
class CompiledExplorationSchedulerTrainPanel:
    panel: CombinationPanel
    packets: tuple[PublicTrainPacket, ...]
    scenarios: Mapping[tuple[str, ...], FrozenRecord]
    packages: Mapping[str, CandidatePackage]


def compile_exploration_scheduler_train_panel(config: FrozenExplorationSchedulerTrainConfig, packets: tuple[PublicTrainPacket, ...]) -> CompiledExplorationSchedulerTrainPanel:
    """Use the registered design, without materializing unexecuted obligations."""
    if not isinstance(config, FrozenExplorationSchedulerTrainConfig) or not isinstance(packets, tuple) or any(not isinstance(p, PublicTrainPacket) for p in packets):
        raise ContractError("combination compilation needs frozen configuration and typed public packets")
    body = config.data()
    by_item = packet_index(body, packets)
    if len(by_item) != len(packets) or set(by_item) != set(body["item_ids"]):
        raise ContractError("exported packets differ from the complete frozen allowlist")
    for item_id, packet in by_item.items():
        binding = body["task_bindings"][item_id]
        if DockerExecutionBroker._has_link_component(packet.csv_path) or packet.csv_path.stat().st_size != binding['csv_byte_count']:
            raise ContractError('exported CSV must be exact regular bytes')
        if (packet.task.identity.data() != binding["identity"] or packet.task.content_hash != binding["task_digest"]
                or hashlib.sha256(packet.csv_path.read_bytes()).hexdigest() != binding["csv_sha256"]
                or packet.receipt.data().get("csv_sha256") != binding["csv_sha256"]
                or packet.receipt.data().get("packet_hash") != packet.task.content_hash):
            raise ContractError("exported public task or CSV differs from its frozen source binding")
    design, arms = _design(body["baseline_digest"])
    packages = {key: CandidatePackage(_record(value, "package")) for key, value in body["packages_by_arm"].items()}
    cells, scenarios = [], {}
    for item_id in body["item_ids"]:
        packet = by_item[item_id]
        for replicate in body["replicates"]:
            scenario = FrozenRecord.from_dict({"schema": "exploration-scheduler-scenario-v1", "obligation_id": _PAIR,
                "design_digest": design.content_hash, "task_digest": packet.task.content_hash,
                "replicate": replicate, "material_digest": FrozenRecord.from_dict(body['materials_by_task'][packet.task.content_hash]).content_hash})
            for arm_id, arm in arms.items():
                cell = PanelCell(_PAIR, packet.task.identity, replicate, "combination", arm_id, arm,
                    packet.task.content_hash, scenario.content_hash, packages[arm.content_hash].digest,
                    _record(body["scorer"], "scorer").content_hash)
                cells.append(cell)
                scenarios[cell.key] = scenario
    panel = CombinationPanel(body["stage"], "train", packets[0].task.identity.split_id, _PAIR, "interaction_on_scale",
        design, FrozenRecord.from_dict({"schema": "combination-package-bundle-v1", "packages": body["packages_by_arm"]}),
        _record(body["acceptance_criteria"], "criteria"), tuple(cells))
    return CompiledExplorationSchedulerTrainPanel(panel, packets, scenarios, packages)


@dataclass(frozen=True)
class ExplorationSchedulerTrainRun:
    compiled: CompiledExplorationSchedulerTrainPanel
    results: tuple[CombinationBenchmarkCellResult | None, ...]
    scores: tuple[ScientificScorerReceipt, ...]
    attempts: tuple[FrozenRecord, ...]
    contrast: FrozenRecord
    receipt: FrozenRecord


from research_loop.modular.combination_train_controller import _service_preflight, _usage


from research_loop.modular.ordinary_provider import (family_service_preflight, model_root, allocation_fields, provider_usage, provider_terminal, provider_scope, bind_runtime_originals)
from research_loop.modular.ordinary_provider import final_provider_gate, final_score_fields, unavailable_provider_contrast, final_usage, final_unused
from research_loop.modular.phase_provider import PhaseProviderSession


def run_exploration_scheduler_train_panel(config: FrozenExplorationSchedulerTrainConfig, *, custody: CustodyStore, snapshot_root: Path,
        export_root: Path, run_root: Path, model: CodexModelPort, audit_verifier: AuditVerifier,
        execution_authority: LinkedExecutionAuthority, scoring_service: CombinationAdaptedScoringService,
        scorer_authority_keys: Mapping[str, bytes], prospective_exporter=None) -> ExplorationSchedulerTrainRun:
    """Run the full frozen factorial once; any failed stage makes it inconclusive."""
    if not isinstance(config, FrozenExplorationSchedulerTrainConfig) or not isinstance(audit_verifier, AuditVerifier):
        raise ContractError("typed train controller, custody and audit dependencies required")
    from evaluation.modular.scorer_process import CombinationScorerProcessClient, serialize_combination_panel
    if type(scoring_service) is not CombinationScorerProcessClient:
        raise ContractError('independent primary scorer process required')
    serialize_combination_panel(scoring_service.panel, exploration_scheduler=True)
    family_service_preflight(config, model, scoring_service, execution_authority, scorer_authority_keys, family='exploration_scheduler')
    native = native_envelope(config.data(), 'exploration_scheduler')
    snapshot, exported, root, _ = _checked_roots(snapshot_root, export_root, run_root, model_root(model, native=native))
    if root.exists() or exported.exists():
        raise ContractError("controller needs unused run and export roots; inspect earlier attempts instead of retrying")
    body = config.data()
    source = CombinationTrainSource(body, custody=custody, prospective_exporter=prospective_exporter,
                                    snapshot=snapshot, exported=exported)
    expected_cells = len(body["item_ids"]) * len(body["replicates"]) * 4
    journal = {"schema": ('exploration-scheduler-train-controller-attempt-v2' if native else 'exploration-scheduler-train-controller-attempt-v1'), "config_digest": config.record.content_hash,
        "status": "exporting", "expected_cells": expected_cells, **(allocation_fields(body, native=True) if native else {'allocated_model_calls':body['max_calls'], 'allocated_model_token_limit':body['max_tokens']}), "allocated_docker_attempts": expected_cells*3,
        "allocated_scorer_calls": expected_cells, "actual_scorer_calls": 0, "scorer_usage": "not_provided_by_transport",
        **({} if native else {'model_policy_sha256':model.frozen_base_context.sha256}), "cells": [], "packet_receipts": []}
    root.mkdir(parents=True, exist_ok=False)
    provider_session = PhaseProviderSession(model, root/'provider-scopes.json') if native else None
    def persist():
        journal["actual_model_usage"] = provider_usage(provider_session, model)
        _write(root / "controller-attempt.json", journal)
    persist()
    try:
        packets = source.export()
        journal["packet_receipts"] = [p.receipt.data() for p in packets]; persist()
        compiled = compile_exploration_scheduler_train_panel(config, packets)
        from evaluation.modular.scorer_process import CombinationScorerProcessClient
        if isinstance(scoring_service, CombinationScorerProcessClient) and scoring_service.panel != compiled.panel:
            raise ContractError("combination scorer process differs from the exported frozen panel")
        if len(compiled.panel.cells) != expected_cells:
            raise ContractError("compiled panel does not cover the frozen allocation")
        # Freeze every cell before any provider call, including future failures.
        journal.update(status="executing", panel_digest=compiled.panel.digest,
            cells=[{"cell": cell.data(), "phase": "planned", "status": "not_started", "scorer_calls": 0,
                    "model_usage_before": None, "model_usage_after": None} for cell in compiled.panel.cells])
        _write(root / "panel.json", {"panel_digest": compiled.panel.digest, "design": compiled.panel.design.data(),
            "config_digest": config.record.content_hash, "cell_plan": [cell.data() for cell in compiled.panel.cells]})
        persist()
    except Exception as exc:
        journal.update(status="blocked_before_execution", error_type=type(exc).__name__)
        persist()
        raise
    broker, broker_error = None, None
    try:
        broker = DockerExecutionBroker([exported, root])
    except Exception as exc:
        broker_error = type(exc).__name__
    by_task = {p.task.content_hash: p for p in packets}
    results, scores, signed_inputs, verified_runtime = [], [], {}, []
    for index, cell in enumerate(compiled.panel.cells):
        row = journal["cells"][index]
        packet = by_task[cell.task_digest]
        result = None
        row.update(phase="execution", status="running", model_usage_before=provider_usage(provider_session, model))
        persist()
        try:
            if broker is None:
                row.update(phase="execution_allocation", status="blocked", reason="broker_preflight_failed", error_type=broker_error)
                continue
            # A poisoned provider ledger is not retried for later cells. They
            # remain explicit planned denominator rows with no fabricated trace.
            if provider_terminal(provider_session, model):
                row.update(phase="model_allocation", status="blocked", reason="prior_model_usage_incomplete")
                continue
            binding = next(v for v in body["task_bindings"].values() if v["identity"] == cell.identity.data())
            if (packet.task.content_hash != binding["task_digest"]
                    or hashlib.sha256(packet.csv_path.read_bytes()).hexdigest() != binding["csv_sha256"]):
                raise ContractError("public source changed after compilation")
            with provider_scope(provider_session, model, cell) as scoped_model:
                result = run_exploration_scheduler_cell(panel=compiled.panel, cell=cell, task=packet.task,
                    scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash],
                    material=FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(body['materials_by_task'][cell.task_digest])),
                    objective=FrozenRecord.from_dict({"panel_digest": compiled.panel.digest}),
                    sidecar=root / "cells" / FrozenRecord.from_dict(cell.data()).content_hash,
                    public_inputs={"public_csv": packet.csv_path}, image=body["image"], broker=broker, model=scoped_model,
                    audit_verifier=audit_verifier, timeout_seconds=body["timeout_seconds"])
            row["runtime"] = PanelReceiptVerifier._runtime_data(result.runtime)
            row.update(phase="source_verification")
            persist()
            if result.cell != cell or result.runtime.cell_key != cell.key:
                raise ContractError("executor returned a foreign cell")
            verified = verify_exploration_scheduler_cell(result, panel=compiled.panel, task=packet.task,
                scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash],
                material=FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(body['materials_by_task'][cell.task_digest])),
                public_inputs={'public_csv':packet.csv_path},broker=broker,image=body['image'],timeout_seconds=body['timeout_seconds'])
            row["runtime_verification"] = verified.data()
            verified_runtime.append(result.runtime)
            if result.runtime.status != "succeeded" or result.solver is None or result.solver.status != "execution_succeeded":
                row.update(status="failed", phase="execution", reason="combination_execution_failed")
                continue
            if native:
                row['provider_seal_digest'] = bind_runtime_originals(provider_session, cell, result.runtime, root/'cells'/FrozenRecord.from_dict(cell.data()).content_hash/'provider-seal.json')
            source = issue_exploration_scheduler_score_input(panel=compiled.panel, result=result, task=packet.task,
                scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash], authority=execution_authority,
                material=FrozenExplorationSchedulerMaterial(FrozenRecord.from_dict(body['materials_by_task'][cell.task_digest])),
                public_inputs={'public_csv':packet.csv_path},broker=broker,image=body['image'],timeout_seconds=body['timeout_seconds'])
            signed_inputs[cell.key] = source
            row["score_input"] = source.data()
            row.update(phase="scoring", scorer_calls=1)
            journal["actual_scorer_calls"] += 1
            persist()  # failed RPC/verification still consumed this opportunity
            score = scoring_service.score_combination(panel=compiled.panel, cell=cell, score_input=source)
            row["scorer_receipt"] = score.receipt.data()
            row.update(phase="score_verification")
            verification = verify_combination_adapted_receipt(score, authority_keys=scorer_authority_keys,
                config=scoring_service.config, panel=compiled.panel, cell=cell, score_input=source,
                execution_authority_keys={execution_authority.authority_id: execution_authority.key})
            scores.append(score)
            if native:
                row['post_score_provider_seal_digest'] = bind_runtime_originals(provider_session, cell, result.runtime, root/'cells'/FrozenRecord.from_dict(cell.data()).content_hash/'post-score-provider-seal.json')
            row.update(status='succeeded', phase='verified', score_verification_digest=verification.content_hash)
        except Exception as exc:
            row.update(status="failed", error_type=type(exc).__name__)
        finally:
            row["model_usage_after"] = provider_usage(provider_session, model)
            if result is not None and result.solver is not None and result.solver.execution is not None:
                row["execution_receipt"] = result.solver.execution.data()
            phase_path = root/'cells'/FrozenRecord.from_dict(cell.data()).content_hash/'phase'
            from research_loop.modular.exploration_scheduler_combination import _read
            events_path = phase_path/'events.jsonl'
            import json
            phase_events = [json.loads(line) for line in _read(events_path).splitlines()] if events_path.is_file() else []
            row['auxiliary_docker_attempts'] = sum(e['kind']=='start' for e in phase_events)
            trace_path = phase_path.parent/'runtime/trace.jsonl'
            row['solver_docker_attempts'] = sum(json.loads(line)['stage']=='execution_request' for line in _read(trace_path).splitlines()) if trace_path.is_file() else 0
            row['docker_attempts'] = row['auxiliary_docker_attempts'] + row['solver_docker_attempts']
            if result is not None: row['phase_receipt'] = result.phase.data()
            results.append(result)
            persist()
    def verify_score(score, cell, panel):
        verify_combination_adapted_receipt(score, authority_keys=scorer_authority_keys, config=scoring_service.config,
            panel=panel, cell=cell, score_input=signed_inputs[cell.key],
            execution_authority_keys={execution_authority.authority_id: execution_authority.key})
    final_gate = final_provider_gate(provider_session, root/'final-provider-ledger.json')
    complete = all(row['status']=='succeeded' for row in journal['cells']) and (not native or final_gate.data()['provider_evidence_eligible'])
    contrast = FrozenRecord.from_dict({"schema": "exploration-scheduler-inconclusive-contrast-v1", "panel_digest": compiled.panel.digest,
        "status": "inconclusive", "reason": "at_least_one_planned_cell_failed_or_unscored", "expected_cells": expected_cells,
        "scored_cells": len(scores), "missing_policy": "incomplete_reject", "scientific_status": "not_measured"})
    if native and not final_gate.data()['provider_evidence_eligible']:
        contrast = unavailable_provider_contrast(compiled.panel, final_gate)
    if complete:
        try:
            contrast = estimate_grouped_contrast(compiled.panel, runtime=verified_runtime, scorer_receipts=scores,
                verifier=CombinationPanelVerifier(scorer_verifier=verify_score))
        except Exception as exc:
            contrast = FrozenRecord.from_dict({"schema": "exploration-scheduler-inconclusive-contrast-v1", "panel_digest": compiled.panel.digest,
                "status": "inconclusive", "reason": "contrast_verification_failed", "error_type": type(exc).__name__,
                "expected_cells": expected_cells, "scored_cells": len(scores), "missing_policy": "incomplete_reject",
                "scientific_status": "not_measured"})
    if native:
        final_gate = final_provider_gate(provider_session, root/'report-provider-ledger.json')
        if not final_gate.data()['provider_evidence_eligible']:
            journal['historical_contrast_before_failed_final_gate'] = contrast.data()
            contrast = unavailable_provider_contrast(compiled.panel, final_gate)
    receipt = FrozenRecord.from_dict({"schema": ('exploration-scheduler-train-controller-receipt-v2' if native else 'exploration-scheduler-train-controller-receipt-v1'), "config_digest": config.record.content_hash,
        "panel_digest": compiled.panel.digest, "expected_cells": expected_cells, "observed_cells": len(journal["cells"]),
        "successful_cells": sum(row["status"] == "succeeded" for row in journal["cells"]), "scored_cells": len(scores), **final_score_fields(final_gate, scores),
        "failed_cells": sum(row["status"] == "failed" for row in journal["cells"]),
        "blocked_cells": sum(row["status"] == "blocked" for row in journal["cells"]),
        "actual_docker_attempts": sum(row['docker_attempts'] for row in journal['cells']),
        "unused_docker_opportunities": 24-sum(row['docker_attempts'] for row in journal['cells']),
        "allocation": body["allocation"], "actual_model_usage": final_usage(final_gate, model), "actual_scorer_calls": journal["actual_scorer_calls"],
        "scorer_usage": "not_provided_by_transport", "contrast": contrast.data(),
        "status": "estimated" if contrast.data()["status"] == "estimated" else "inconclusive",
        "scientific_effectiveness_proven": False, "validation_opened": False, "pruned_cells": []})
    _write(root / "controller-receipt.json", receipt.data())
    journal["status"] = receipt.data()["status"]
    journal.update(actual_model_usage=receipt.data()['actual_model_usage']); _write(root/'controller-attempt.json',journal)
    return ExplorationSchedulerTrainRun(compiled, tuple(results), tuple(scores), tuple(FrozenRecord.from_dict(row) for row in journal["cells"]), contrast, receipt)
