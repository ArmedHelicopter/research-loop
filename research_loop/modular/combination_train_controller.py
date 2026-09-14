"""Custody -> complete M4/M5 factorial -> signed adapted scores -> contrast.

This trusted train-only controller preserves every planned cell.  Execution
and scoring remain separate authorities; component signatures are not a claim
of independently deployed processes or scientific validity.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from evaluation.modular.custody import CustodyStore
from evaluation.modular.train_io import PublicTrainPacket
from research_loop.modular.combination_train_source import (
    CombinationTrainSource, source_schema_matches, source_item_matches, packet_index,
)
from evaluation.modular.combination_scoring import (
    CombinationAdaptedScoringService, issue_combination_score_input, verify_combination_adapted_receipt,
)
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.combination_panels import CombinationPanel, CombinationPanelVerifier
from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.combination_benchmark_driver import (
    CombinationBenchmarkCellResult, run_m4_m5_combination_benchmark_cell,
    verify_m4_m5_combination_benchmark_cell,
)
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.model_port import CodexModelPort, _validate_schema, _schema_witness
from research_loop.modular.grok_train_solver import GrokTrainModelPort, replay_grok_train_ledger
from research_loop.modular.grok_headless_train_solver import GrokHeadlessTrainModelPort, replay_headless_train_ledger
from research_loop.modular.train_provider_headless import configuration as headless_configuration
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell, PanelReceiptVerifier, ScientificScorerReceipt
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import _checked_roots, _reviewed_model_policy, _write
from research_loop.modular.m4_m5_useful_controls import source_contract_body
from research_loop.ontology import ContractError


SLOTS = ("m4_plan", "m5_mechanism", "m5_measurement", "analysis_program", "final_answer")
_PAIR = "pair:M4+M5"
_ANALYSIS = {"schema": "frozen-combination-contrast-analysis-v1", "direction": "higher_better",
             "value_range": [0.0, 1.0], "scale": "unit", "missing_policy": "incomplete_reject",
             "group_weighting": "task_replicate_mean_then_equal_group_mean"}


def _native_schema(body):
    return body.get('schema') in ('m4-m5-train-controller-config-v4','m4-m5-train-controller-config-v5')


def _native_model(model):
    return isinstance(model,GrokTrainModelPort) or type(model) is GrokHeadlessTrainModelPort


def _replay_native_model(model):
    if type(model) is GrokHeadlessTrainModelPort:
        headless_configuration(model)
        replay_headless_train_ledger(model)
    elif isinstance(model,GrokTrainModelPort):
        replay_grok_train_ledger(model)
    else:
        raise ContractError('exact native TRAIN port required')


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
    design = default_compatibility(baseline).conditional_factorial(("M4", "M5"))
    arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in design.data()["cells"] if row["status"] == "executable"}
    if set(arms) != {"00", "10", "01", "11"} or design.data()["interaction_status"] != "identifiable":
        raise ContractError("registered compatibility does not admit the complete M4/M5 factorial")
    return design, arms


@dataclass(frozen=True)
class FrozenM4M5TrainConfig:
    """Complete task, package, source, scorer and opportunity allocation."""
    record: FrozenRecord

    def __post_init__(self):
        if not isinstance(self.record, FrozenRecord):
            raise ContractError("combination controller configuration must be frozen")
        body = self.record.data()
        fields = {"schema", "domain", "stage", "item_ids", "task_bindings", "baseline_digest", "packages_by_arm",
                  "scorer", "scorer_handle_bindings", "acceptance_criteria", "replicates", "model", "effort",
                  "max_calls", "max_tokens", "schemas", "allocation", "image", "timeout_seconds"}
        normalized = source_contract_body(body)
        if not source_schema_matches(normalized, fields, "m4-m5-train-controller-config-v1") or body["domain"] != "train":
            raise ContractError("controller supports the exact train-only M4/M5 configuration")
        if not isinstance(body["stage"], str) or not body["stage"].strip() or not _names(body["item_ids"]) or not _names(body["replicates"]):
            raise ContractError("stage, train allowlist and replicates must be nonempty and unique")
        if not _digest(body["baseline_digest"]):
            raise ContractError("combination baseline must be a digest")
        bindings = body["task_bindings"]
        if not isinstance(bindings, Mapping) or set(bindings) != set(body["item_ids"]):
            raise ContractError("task/source bindings must exactly cover the allowlist")
        identities = []
        for item_id, row in bindings.items():
            if (not isinstance(row, Mapping) or set(row) != {"identity", "task_digest", "csv_sha256"}
                    or not _digest(row["task_digest"]) or not _digest(row["csv_sha256"])):
                raise ContractError("task/source binding is malformed")
            identity = DataIdentity.parse(row["identity"])
            identity.require_train()
            if not source_item_matches(body, item_id, identity):
                raise ContractError("allowlist and task identity differ")
            identities.append(identity)
        if {i.benchmark for i in identities} != {"blade", "discoverybench"} or len({i.split_id for i in identities}) != 1:
            raise ContractError("controller requires both core benchmarks in one frozen train split")
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
        handles = body["scorer_handle_bindings"]
        identity_digests = {FrozenRecord.from_dict(i.data()).content_hash for i in identities}
        if not isinstance(handles, Mapping) or set(handles) != identity_digests or any(not _digest(v) for v in handles.values()):
            raise ContractError("scorer handles must exactly bind the frozen train identities")
        if _record(body["acceptance_criteria"], "criteria").data().get("contrast_analysis") != _ANALYSIS:
            raise ContractError("controller requires the existing frozen incomplete-reject contrast semantics")
        cells = len(identities) * len(body["replicates"]) * 4
        expected_allocation = {"model_slots_per_cell": list(SLOTS), "docker_attempts_per_cell": 1,
            "scorer_calls_per_cell": 1, "scorer_call_limit": cells, "scorer_token_accounting": "transport_not_provided"}
        if (not isinstance(body["allocation"], Mapping) or body["allocation"] != expected_allocation
                or any(type(body["allocation"].get(k)) is not int for k in
                       ("docker_attempts_per_cell", "scorer_calls_per_cell", "scorer_call_limit"))):
            raise ContractError("model slots, Docker attempts and scorer opportunities must be equally frozen")
        grok = _native_schema(body)
        if grok:
            if len(identities) != 2 or len(body['replicates']) != 1 or cells != 8:
                raise ContractError('native versions admit exactly one eight-cell core TRAIN panel')
            provider = body.get('provider')
            expected = {'kind':'grok-acp-public-train-v1','model':'grok-4.6','opportunity_contract':'public-train-main-and-initial-title-v1',
                'included_only':True,'api_key_route_permitted':False,'main_calls':cells*len(SLOTS),
                'possible_initial_title_calls':cells*len(SLOTS),'main_output_caps':{'m4_plan':2048,'m5_mechanism':2048,'m5_measurement':2048,'analysis_program':8192,'final_answer':2048},
                'input_byte_cap_per_request':262144,'observed_main_token_cap':131072,'title_requested_output_cap':100,
                'wall_timeout_seconds':60,'max_retries':0,'title_usage_and_all_call_totals':'unknown'}
            headless=body['schema']=='m4-m5-train-controller-config-v5'
            if headless:
                expected.update(kind='grok-headless-public-train-v1',
                    account_read_recovery={'schema':'headless-account-read-recovery-v1','max_attempts':2})
                if not isinstance(provider,dict) or type(provider.get('account_read_recovery',{}).get('max_attempts')) is not int:
                    raise ContractError('headless account recovery requires an exact integer bound')
            if provider != expected or body['model'] != 'grok-4.6' or body['effort'] != ('low' if headless else 'native_acp'):
                raise ContractError('exact versioned public Grok TRAIN provider allocation required')
        if ((not grok and (body["model"] != "gpt-5.6-luna" or body["effort"] != "low"))
                or (grok and (body['max_tokens'] != 131072 * cells * len(SLOTS)))
                or type(body["max_calls"]) is not int or body["max_calls"] != cells * len(SLOTS)
                or type(body["max_tokens"]) is not int or body["max_tokens"] < 1
                or type(body["timeout_seconds"]) is not int or not 1 <= body["timeout_seconds"] <= 120):
            raise ContractError("model and exact full-panel budgets must be frozen")
        if (not isinstance(body["image"], str) or "@sha256:" not in body["image"]
                or not _digest(body["image"].rsplit("@sha256:", 1)[1])):
            raise ContractError("Docker image must be content pinned")
        schemas = body["schemas"]
        if not isinstance(schemas, Mapping) or set(schemas) != set(SLOTS):
            raise ContractError("exact five response schemas are required")
        for schema in schemas.values():
            if not isinstance(schema, Mapping) or schema.get("type") != "object":
                raise ContractError("response schemas must describe objects")
            _validate_schema(schema, _schema_witness(schema))

    def data(self):
        return self.record.data()


@dataclass(frozen=True)
class CompiledM4M5TrainPanel:
    panel: CombinationPanel
    packets: tuple[PublicTrainPacket, ...]
    scenarios: Mapping[tuple[str, ...], FrozenRecord]
    packages: Mapping[str, CandidatePackage]


def compile_m4_m5_train_panel(config: FrozenM4M5TrainConfig, packets: tuple[PublicTrainPacket, ...]) -> CompiledM4M5TrainPanel:
    """Use the registered design, without materializing unexecuted obligations."""
    if not isinstance(config, FrozenM4M5TrainConfig) or not isinstance(packets, tuple) or any(not isinstance(p, PublicTrainPacket) for p in packets):
        raise ContractError("combination compilation needs frozen configuration and typed public packets")
    body = config.data()
    by_item = packet_index(body, packets)
    if len(by_item) != len(packets) or set(by_item) != set(body["item_ids"]):
        raise ContractError("exported packets differ from the complete frozen allowlist")
    for item_id, packet in by_item.items():
        binding = body["task_bindings"][item_id]
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
            scenario = FrozenRecord.from_dict({"schema": "combination-public-scenario-v1", "obligation_id": _PAIR,
                "design_digest": design.content_hash, "task_digest": packet.task.content_hash,
                "replicate": replicate, "status": "predeclared", **({
                    "schema": "combination-public-scenario-v2", "execution_recipe": body["execution_recipe"]
                } if "execution_recipe" in body else {})})
            for arm_id, arm in arms.items():
                cell = PanelCell(_PAIR, packet.task.identity, replicate, "combination", arm_id, arm,
                    packet.task.content_hash, scenario.content_hash, packages[arm.content_hash].digest,
                    _record(body["scorer"], "scorer").content_hash)
                cells.append(cell)
                scenarios[cell.key] = scenario
    panel = CombinationPanel(body["stage"], "train", packets[0].task.identity.split_id, _PAIR, "interaction_on_scale",
        design, FrozenRecord.from_dict({"schema": "combination-package-bundle-v1", "packages": body["packages_by_arm"]}),
        _record(body["acceptance_criteria"], "criteria"), tuple(cells))
    return CompiledM4M5TrainPanel(panel, packets, scenarios, packages)


@dataclass(frozen=True)
class M4M5TrainRun:
    compiled: CompiledM4M5TrainPanel
    results: tuple[CombinationBenchmarkCellResult | None, ...]
    scores: tuple[ScientificScorerReceipt, ...]
    attempts: tuple[FrozenRecord, ...]
    contrast: FrozenRecord
    receipt: FrozenRecord


def _service_preflight(config, model, service, execution_authority, scorer_keys):
    from evaluation.modular.scorer_process import CombinationScorerProcessClient
    body = config.data()
    grok = _native_schema(body)
    admitted_model = (type(model) is GrokHeadlessTrainModelPort if body.get('schema')=='m4-m5-train-controller-config-v5'
        else isinstance(model,GrokTrainModelPort) if grok else isinstance(model,CodexModelPort))
    if not admitted_model or not isinstance(service, (CombinationAdaptedScoringService, CombinationScorerProcessClient)) or not isinstance(execution_authority, LinkedExecutionAuthority):
        raise ContractError("real model port, independent scoring service and execution authority are required")
    if not grok: _reviewed_model_policy(model)
    if grok:
        declared=body['provider']
        if type(model) is GrokHeadlessTrainModelPort:
            headless_configuration(model)
            if model.account_read_recovery != declared['account_read_recovery']:
                raise ContractError('headless recovery differs from frozen declaration')
        if (model.provider_kind != declared['kind'] or model.slot_output_caps != declared['main_output_caps']
                or set(model.slot_input_byte_caps) != set(SLOTS)
                or any(model.slot_input_byte_caps[s] != declared['input_byte_cap_per_request'] for s in SLOTS)
                or model.observed_main_token_cap != declared['observed_main_token_cap']
                or model.ledger['config'].get('frozen_files') != model.frozen_files):
            raise ContractError('live Grok provider bounds or source binding drift')
    if (model.model != body["model"] or model.effort != body["effort"] or model.max_calls != body["max_calls"]
            or (not grok and model.max_tokens != body["max_tokens"]) or model.schemas != body["schemas"]
            or model.ledger.get("calls") or model.ledger.get("tokens") != 0 or model.ledger.get("usage_incomplete") is not False):
        raise ContractError("live model configuration/schemas or fresh budget ledger drift")
    if isinstance(service, CombinationScorerProcessClient):
        service.assert_configuration(config=ScorerConfig(_record(body["scorer"], "scorer")),
            task_handle_bindings=body["scorer_handle_bindings"],
            execution_authority_keys={execution_authority.authority_id: execution_authority.key}, scorer_authority_keys=scorer_keys)
        return
    # These are trusted in-process component dependencies. Checking both key
    # sets prevents a caller from passing a verifier unrelated to the service.
    if (not isinstance(scorer_keys, Mapping) or set(scorer_keys) != {service._authority.authority_id}
            or scorer_keys.get(service._authority.authority_id) != service._authority.key
            or service._execution_keys != {execution_authority.authority_id: execution_authority.key}
            or execution_authority.authority_id in scorer_keys or execution_authority.key in scorer_keys.values()):
        raise ContractError("live execution and scoring authorities must match and be independent")
    if service.config.record != _record(body["scorer"], "scorer"):
        raise ContractError("live scoring configuration drift")
    handle_bindings = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in service._handles.items()
                       if isinstance(value, str) and value}
    if handle_bindings != body["scorer_handle_bindings"] or len(handle_bindings) != len(service._handles):
        raise ContractError("live scorer task delegation differs from frozen handle bindings")


def _usage(model):
    base={"model_calls": len(model.ledger["calls"]), "known_model_tokens": model.ledger["tokens"],
            "model_usage_incomplete": model.ledger["usage_incomplete"]}
    if _native_model(model):
        base.update(possible_initial_title_opportunities=len(model.ledger['calls']),
            title_and_all_opportunity_settlement='unknown')
    return base


def _verify_grok_cell_native_binding(model, runtime):
    """Every public trace call must be the matching immutable native original."""
    events=[FrozenRecord(line).data() for line in runtime.trace_path.read_text(encoding='utf-8').splitlines()]
    requests=[e['data']['request'] for e in events if e['stage']=='model_request']
    responses=[e['data']['response'] for e in events if e['stage']=='model_response']
    rows=model.ledger['calls'][-len(requests):]
    if len(requests)!=5 or len(responses)!=5 or len(rows)!=5:
        raise ContractError('cell lacks exactly five native public solver opportunities')
    for request,response,row in zip(requests,responses,rows,strict=True):
        original=FrozenRecord.from_dict(json.loads((model.calls_root/f"{row['id']:04d}-{row['slot']}"/'request.private.json').read_text(encoding='utf-8')))
        saved=FrozenRecord.from_dict(json.loads((model.calls_root/f"{row['id']:04d}-{row['slot']}"/'response.private.json').read_text(encoding='utf-8')))
        if (row['status']!='succeeded' or request.get('slot') != row['slot'] or FrozenRecord.from_dict(request).content_hash != original.content_hash
                or FrozenRecord.from_dict(response).content_hash != saved.content_hash or row['response_sha256'] != saved.content_hash
                or request.get('task') != original.data().get('task') or request.get('lock_digest') != original.data().get('lock_digest')):
            raise ContractError('runtime trace differs from native public solver originals')


def _grok_final_provider_gate(model):
    """Fresh original replay after all side effects; old scores remain history."""
    body = {'schema': 'm4-m5-final-native-provenance-v1',
            'current_originals_verified': False, 'score_eligible': False}
    try:
        _replay_native_model(model)
    except ContractError as exc:
        return {**body, 'status': 'ineligible', 'reason': 'native_original_replay_failed',
                'error_type': type(exc).__name__}
    body['current_originals_verified'] = True
    if model.ledger['usage_incomplete']:
        return {**body, 'status': 'ineligible', 'reason': 'native_usage_incomplete'}
    return {**body, 'status': 'verified', 'score_eligible': True}


def run_m4_m5_train_panel(config: FrozenM4M5TrainConfig, *, custody: CustodyStore | None, snapshot_root: Path,
        export_root: Path, run_root: Path, model: CodexModelPort, audit_verifier: AuditVerifier,
        execution_authority: LinkedExecutionAuthority, scoring_service: CombinationAdaptedScoringService,
        scorer_authority_keys: Mapping[str, bytes], prospective_exporter=None) -> M4M5TrainRun:
    """Run the full frozen factorial once; any failed stage makes it inconclusive."""
    if not isinstance(config, FrozenM4M5TrainConfig) or not isinstance(audit_verifier, AuditVerifier):
        raise ContractError("typed train controller, custody and audit dependencies required")
    _service_preflight(config, model, scoring_service, execution_authority, scorer_authority_keys)
    snapshot, exported, root, _ = _checked_roots(snapshot_root, export_root, run_root, model.root)
    if root.exists() or exported.exists():
        raise ContractError("controller needs unused run and export roots; inspect earlier attempts instead of retrying")
    body = config.data()
    native = _native_model(model)
    source = CombinationTrainSource(body, custody=custody, prospective_exporter=prospective_exporter,
                                  snapshot=snapshot, exported=exported)
    expected_cells = len(body["item_ids"]) * len(body["replicates"]) * 4
    journal = {"schema": ("m4-m5-train-controller-attempt-v2" if native else "m4-m5-train-controller-attempt-v1"), "config_digest": config.record.content_hash,
        "status": "exporting", "expected_cells": expected_cells, "allocated_model_calls": body["max_calls"],
        "allocated_model_token_limit": body["max_tokens"], "allocated_docker_attempts": expected_cells,
        "allocated_scorer_calls": expected_cells, "actual_scorer_calls": 0, "scorer_usage": "not_provided_by_transport",
        "model_policy_sha256": None if _native_schema(body) else model.frozen_base_context.sha256, "provider_kind": getattr(model, 'provider_kind', 'codex-cli'), "cells": [], "packet_receipts": []}
    root.mkdir(parents=True, exist_ok=False)
    def persist():
        journal["actual_model_usage"] = _usage(model)
        _write(root / "controller-attempt.json", journal)
    persist()
    try:
        packets = source.export()
        journal["packet_receipts"] = [p.receipt.data() for p in packets]
        compiled = compile_m4_m5_train_panel(config, packets)
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
        row.update(phase="execution", status="running", model_usage_before=_usage(model))
        persist()
        try:
            if broker is None:
                row.update(phase="execution_allocation", status="blocked", reason="broker_preflight_failed", error_type=broker_error)
                continue
            # A poisoned provider ledger is not retried for later cells. They
            # remain explicit planned denominator rows with no fabricated trace.
            if model.ledger["usage_incomplete"]:
                row.update(phase="model_allocation", status="blocked", reason="prior_model_usage_incomplete")
                continue
            binding = next(b for b in body["task_bindings"].values() if b["identity"] == cell.identity.data())
            if (packet.task.content_hash != binding["task_digest"]
                    or hashlib.sha256(packet.csv_path.read_bytes()).hexdigest() != binding["csv_sha256"]):
                raise ContractError("public source changed after compilation")
            result = run_m4_m5_combination_benchmark_cell(panel=compiled.panel, cell=cell, task=packet.task,
                scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash],
                objective=FrozenRecord.from_dict({"panel_digest": compiled.panel.digest}),
                sidecar=root / "cells" / FrozenRecord.from_dict(cell.data()).content_hash,
                public_inputs={"public_csv": packet.csv_path}, image=body["image"], broker=broker, model=model,
                audit_verifier=audit_verifier, timeout_seconds=body["timeout_seconds"])
            row["runtime"] = PanelReceiptVerifier._runtime_data(result.runtime)
            row.update(phase="source_verification")
            persist()
            if result.cell != cell or result.runtime.cell_key != cell.key:
                raise ContractError("executor returned a foreign cell")
            verified = verify_m4_m5_combination_benchmark_cell(result, panel=compiled.panel, task=packet.task,
                scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash])
            row["runtime_verification"] = verified.data()
            verified_runtime.append(result.runtime)
            if result.runtime.status != "succeeded" or result.solver is None or result.solver.status != "execution_succeeded":
                row.update(status="failed", phase="execution", reason="combination_execution_failed")
                continue
            if _native_model(model):
                _replay_native_model(model)
                _verify_grok_cell_native_binding(model, result.runtime)
            source = issue_combination_score_input(panel=compiled.panel, result=result, task=packet.task,
                scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash], authority=execution_authority)
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
            # Preserve the actual authenticated scorer response even when a
            # subsequent original replay makes it ineligible for a contrast.
            scores.append(score)
            if native:
                row.update(phase='post_score_native_verification')
                _replay_native_model(model)
                _verify_grok_cell_native_binding(model, result.runtime)
            row.update(status="succeeded", phase="verified", score_verification_digest=verification.content_hash)
        except Exception as exc:
            row.update(status="failed", error_type=type(exc).__name__)
        finally:
            row["model_usage_after"] = _usage(model)
            if result is not None and result.solver is not None and result.solver.execution is not None:
                row["execution_receipt"] = result.solver.execution.data()
            results.append(result)
            persist()
    def verify_score(score, cell, panel):
        verify_combination_adapted_receipt(score, authority_keys=scorer_authority_keys, config=scoring_service.config,
            panel=panel, cell=cell, score_input=signed_inputs[cell.key],
            execution_authority_keys={execution_authority.authority_id: execution_authority.key})
    final_gate = _grok_final_provider_gate(model) if native else None
    complete = all(row["status"] == "succeeded" for row in journal["cells"]) and (not native or final_gate['score_eligible'])
    contrast = FrozenRecord.from_dict({"schema": "m4-m5-inconclusive-contrast-v1", "panel_digest": compiled.panel.digest,
        "status": "inconclusive", "reason": "at_least_one_planned_cell_failed_or_unscored", "expected_cells": expected_cells,
        "scored_cells": len(scores), "missing_policy": "incomplete_reject", "scientific_status": "not_measured"})
    if complete:
        try:
            contrast = estimate_grouped_contrast(compiled.panel, runtime=verified_runtime, scorer_receipts=scores,
                verifier=CombinationPanelVerifier(scorer_verifier=verify_score))
        except Exception as exc:
            contrast = FrozenRecord.from_dict({"schema": "m4-m5-inconclusive-contrast-v1", "panel_digest": compiled.panel.digest,
                "status": "inconclusive", "reason": "contrast_verification_failed", "error_type": type(exc).__name__,
                "expected_cells": expected_cells, "scored_cells": len(scores), "missing_policy": "incomplete_reject",
                "scientific_status": "not_measured"})
    # Contrast verification also reads original journals. Close the provider
    # evidence again at the reporting boundary, without another model call.
    if native:
        if final_gate['score_eligible']:
            final_gate = _grok_final_provider_gate(model)
        if not final_gate['score_eligible']:
            if contrast.data()['status'] == 'estimated':
                journal['historical_contrast_before_failed_final_gate'] = contrast.data()
            contrast = FrozenRecord.from_dict({'schema': 'm4-m5-inconclusive-contrast-v1',
                'panel_digest': compiled.panel.digest, 'status': 'inconclusive',
                'reason': 'final_native_provider_evidence_ineligible', 'expected_cells': expected_cells,
                'scored_cells': len(scores), 'eligible_scored_cells': 0,
                'missing_policy': 'incomplete_reject', 'scientific_status': 'not_measured'})
        journal['native_final_verification'] = final_gate
        journal['eligible_scored_cells'] = len(scores) if final_gate['score_eligible'] else 0
    receipt = FrozenRecord.from_dict({"schema": ("m4-m5-train-controller-receipt-v2" if native else "m4-m5-train-controller-receipt-v1"), "config_digest": config.record.content_hash,
        "panel_digest": compiled.panel.digest, "expected_cells": expected_cells, "observed_cells": len(journal["cells"]),
        "successful_cells": sum(row["status"] == "succeeded" for row in journal["cells"]), "scored_cells": len(scores),
        "failed_cells": sum(row["status"] == "failed" for row in journal["cells"]),
        "blocked_cells": sum(row["status"] == "blocked" for row in journal["cells"]),
        **({'native_final_verification': final_gate,
            'eligible_scored_cells': len(scores) if final_gate['score_eligible'] else 0} if native else {}),
        "allocation": body["allocation"], "actual_model_usage": _usage(model), "actual_scorer_calls": journal["actual_scorer_calls"],
        "scorer_usage": "not_provided_by_transport", "contrast": contrast.data(),
        "status": "estimated" if contrast.data()["status"] == "estimated" else "inconclusive",
        "scientific_effectiveness_proven": False, "validation_opened": False, "pruned_cells": []})
    _write(root / "controller-receipt.json", receipt.data())
    journal["status"] = receipt.data()["status"]
    persist()
    return M4M5TrainRun(compiled, tuple(results), tuple(scores), tuple(FrozenRecord.from_dict(row) for row in journal["cells"]), contrast, receipt)
