"""Train-only linked adapted scoring over a deliberately small stdio boundary.

The process owns the frozen panel, train-reference store, authority keys and
evaluator configuration.  Its client sends one declared cell key and its
signed linked input, and receives an opaque scorer receipt.  This is process
wiring, not an OS isolation or an asymmetric-trust claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from queue import Empty, Queue
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from threading import Thread
import uuid
from typing import Any, Callable, Mapping, TextIO

from evaluation.modular.evaluator_model_port import CodexEvaluatorModelPort
from evaluation.modular.linked_scoring import LinkedAdaptedScoringService, LinkedExecutionAuthority
from evaluation.modular.combination_scoring import CombinationAdaptedScoringService
from evaluation.modular.reference_store import FrozenTrainReferenceResolver
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint, FrozenRubricTransport, ScorerConfig
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.model_port import FrozenBaseContextPolicy
from research_loop.modular.panel_receipts import CombinationObligations, FrozenPanel, PanelCell, ScientificScorerReceipt
from research_loop.ontology import ContractError, canonical, digest


_CONFIG_SCHEMA = "linked-scorer-process-config-v1"
_PANEL_SCHEMA = "linked-scorer-process-panel-v1"
_REQUEST_SCHEMA = "linked-scorer-process-request-v1"
_RESPONSE_SCHEMA = "linked-scorer-process-response-v1"
_JOURNAL_SCHEMA = "linked-scorer-process-journal-v1"
_COMBINATION_CONFIG_SCHEMA = "combination-scorer-process-config-v1"


def _sha(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{name} must be a sha256 digest")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{name} must be nonempty text")
    return value


def _absolute(value: object, name: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ContractError(f"{name} must be an absolute path")
    return Path(value)


def _key(path: Path, name: str) -> bytes:
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"{name} is unavailable") from exc
    if len(value) < 32:
        raise ContractError(f"{name} must contain at least 32 bytes")
    return value


def serialize_frozen_panel(panel: FrozenPanel) -> dict[str, object]:
    """Return complete typed panel material that can be digest-reconstructed."""
    if not isinstance(panel, FrozenPanel):
        raise ContractError("scorer process needs a FrozenPanel")
    return {"schema": _PANEL_SCHEMA, "panel_digest": panel.digest, "panel": {
        "stage": panel.stage, "domain": panel.domain, "split_digest": panel.split_digest,
        "candidate_digest": panel.candidate_digest, "scope_ids": list(panel.scope_ids),
        "legal_arm_grids": {name: record.data() for name, record in panel.legal_arm_grids.items()},
        "acceptance_criteria": panel.acceptance_criteria.data(),
        "cells": [cell.data() for cell in panel.cells], "combinations": panel.combinations.data(),
        "required_benchmarks": list(panel.required_benchmarks),
    }}


def parse_frozen_panel(value: object) -> FrozenPanel:
    if not isinstance(value, Mapping) or set(value) != {"schema", "panel_digest", "panel"} or value["schema"] != _PANEL_SCHEMA:
        raise ContractError("scorer process panel serialization is invalid")
    expected_digest = _digest(value["panel_digest"], "panel digest")
    body = value["panel"]
    expected = {"stage", "domain", "split_digest", "candidate_digest", "scope_ids", "legal_arm_grids", "acceptance_criteria", "cells", "combinations", "required_benchmarks"}
    if not isinstance(body, Mapping) or set(body) != expected:
        raise ContractError("scorer process panel body is invalid")
    grids = body["legal_arm_grids"]
    combinations = body["combinations"]
    if (not isinstance(grids, Mapping) or not isinstance(body["scope_ids"], list) or not isinstance(body["cells"], list)
            or not isinstance(combinations, Mapping) or set(combinations) != {"pairs", "triples", "full_arm", "leave_one_out", "status"}
            or combinations["status"] != "routing_only" or not isinstance(body["required_benchmarks"], list)):
        raise ContractError("scorer process panel fields are invalid")
    try:
        cells = tuple(PanelCell(
            coverage_id=row["coverage_id"], identity=DataIdentity.parse(row["identity"]), replicate=row["replicate"],
            variant=row["variant"], arm_id=row["arm_id"], runtime_arm=FrozenRecord.from_dict(row["runtime_arm"]),
            task_digest=row["task_digest"], scenario_digest=row["scenario_digest"], package_digest=row["package_digest"],
            scorer_digest=row["scorer_digest"],
        ) for row in body["cells"] if isinstance(row, Mapping))
        if len(cells) != len(body["cells"]):
            raise ValueError("invalid cell")
        panel = FrozenPanel(
            str(body["stage"]), str(body["domain"]), str(body["split_digest"]), str(body["candidate_digest"]),
            tuple(body["scope_ids"]), {str(name): FrozenRecord.from_dict(record) for name, record in grids.items()},
            FrozenRecord.from_dict(body["acceptance_criteria"]), cells,
            CombinationObligations(tuple(tuple(pair) for pair in combinations["pairs"]),
                                   tuple(tuple(triple) for triple in combinations["triples"]),
                                   tuple(combinations["full_arm"]), tuple(combinations["leave_one_out"])),
            tuple(body["required_benchmarks"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("scorer process panel cannot be reconstructed") from exc
    if panel.digest != expected_digest:
        raise ContractError("scorer process panel digest mismatch")
    return panel


def serialize_combination_panel(panel: CombinationPanel, *, lineage: bool = False,
                                retrieval_review: bool = False, admission: bool = False, exploration_scheduler: bool = False,
                                state_prediction: bool = False, state_retrieval: bool = False, state_exploration: bool = False, state_scheduling: bool = False, state_improvement: bool = False, mechanism_exploration: bool = False, mechanism_scheduling: bool = False, mechanism_improvement: bool = False, admission_prediction_exploration: bool = False, lineage_retrieval_improvement: bool = False, execution_improvement: bool = False, full_loo: bool = False, joint_train: bool = False) -> dict[str, object]:
    """Keep each explicitly opted-in combination family in a closed scope."""
    from research_loop.modular.lineage_combination_driver import DESIGNS as LINEAGE_DESIGNS
    from research_loop.modular.retrieval_review_combination_driver import DESIGNS as RETRIEVAL_DESIGNS, registered_design
    from research_loop.modular.admission_combination import DESIGNS as ADMISSION_DESIGNS
    from research_loop.modular.state_prediction_combination_driver import DESIGNS as STATE_PREDICTION_DESIGNS, registered_design as state_prediction_design
    from research_loop.modular.combinations import default_compatibility
    from research_loop.modular.state_retrieval_combination_driver import DESIGNS as STATE_RETRIEVAL_DESIGNS, registered_design as state_retrieval_design
    from research_loop.modular.state_exploration_combination_driver import DESIGNS as STATE_EXPLORATION_DESIGNS, registered_design as state_exploration_design
    from research_loop.modular.state_scheduling_combination_driver import DESIGNS as STATE_SCHEDULING_DESIGNS, registered_design as state_scheduling_design
    from research_loop.modular.state_improvement_panel import StateImprovementPanel, DESIGNS as STATE_IMPROVEMENT_DESIGNS
    from research_loop.modular.mechanism_exploration_combination_driver import DESIGNS as MECHANISM_EXPLORATION_DESIGNS, registered_design as mechanism_exploration_design
    from research_loop.modular.mechanism_scheduling_combination_driver import DESIGNS as MECHANISM_SCHEDULING_DESIGNS, registered_design as mechanism_scheduling_design
    from research_loop.modular.mechanism_improvement_panel import MechanismImprovementPanel, DESIGNS as MECHANISM_IMPROVEMENT_DESIGNS
    from research_loop.modular.admission_prediction_exploration_driver import DESIGNS as ADMISSION_PREDICTION_EXPLORATION_DESIGNS, registered_design as admission_prediction_exploration_design
    from research_loop.modular.lineage_retrieval_improvement_panel import LineageRetrievalImprovementPanel, DESIGNS as LINEAGE_RETRIEVAL_IMPROVEMENT_DESIGNS
    from research_loop.modular.execution_improvement_panel import ExecutionImprovementPanel, DESIGNS as EXECUTION_IMPROVEMENT_DESIGNS
    from research_loop.modular.full_loo_panel import FullLooPanel, OBLIGATION as C4_OBLIGATION
    from research_loop.modular.joint_train_panel import JointTrainPanel
    from research_loop.modular.joint_train_protocol import OBLIGATION as C5_OBLIGATION
    flags = (joint_train, full_loo, lineage, retrieval_review, admission, exploration_scheduler, state_prediction, state_retrieval, state_exploration, state_scheduling, state_improvement, mechanism_exploration, mechanism_scheduling, mechanism_improvement, admission_prediction_exploration, lineage_retrieval_improvement, execution_improvement)
    if any(type(flag) is not bool for flag in flags) or sum(flags) > 1:
        raise ContractError('combination scorer requires one strict explicit scope')
    permitted = ((C5_OBLIGATION,) if joint_train else (C4_OBLIGATION,) if full_loo else EXECUTION_IMPROVEMENT_DESIGNS if execution_improvement else LINEAGE_RETRIEVAL_IMPROVEMENT_DESIGNS if lineage_retrieval_improvement else ADMISSION_PREDICTION_EXPLORATION_DESIGNS if admission_prediction_exploration else MECHANISM_IMPROVEMENT_DESIGNS if mechanism_improvement else MECHANISM_SCHEDULING_DESIGNS if mechanism_scheduling else MECHANISM_EXPLORATION_DESIGNS if mechanism_exploration else STATE_SCHEDULING_DESIGNS if state_scheduling else STATE_EXPLORATION_DESIGNS if state_exploration else STATE_IMPROVEMENT_DESIGNS if state_improvement else STATE_RETRIEVAL_DESIGNS if state_retrieval else STATE_PREDICTION_DESIGNS if state_prediction else ('pair:M7+M8',) if exploration_scheduler
                 else LINEAGE_DESIGNS if lineage else RETRIEVAL_DESIGNS if retrieval_review
                 else ADMISSION_DESIGNS if admission else ('pair:M4+M5',))
    if not isinstance(panel, CombinationPanel) or panel.obligation_id not in permitted or panel.domain != "train":
        raise ContractError("process scoring combination is outside its explicit closed scope")
    if (admission_prediction_exploration and panel.design != admission_prediction_exploration_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])
            or mechanism_scheduling and panel.design != mechanism_scheduling_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])
            or mechanism_exploration and panel.design != mechanism_exploration_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])
            or state_scheduling and panel.design != state_scheduling_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])
            or state_exploration and panel.design != state_exploration_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])
            or retrieval_review and panel.design != registered_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])
            or state_prediction and panel.design != state_prediction_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])
            or state_retrieval and panel.design != state_retrieval_design(panel.obligation_id, panel.design.data()['compatibility']['baseline_digest'])):
        raise ContractError('process scoring combination design differs from the exact registered design')
    if joint_train and type(panel) is not JointTrainPanel:
        raise ContractError('exact versioned common C5 TRAIN panel required')
    if joint_train:
        panel.__post_init__()
    if full_loo and type(panel) is not FullLooPanel:
        raise ContractError('exact versioned C4 panel required')
    if execution_improvement and type(panel) is not ExecutionImprovementPanel:
        raise ContractError('exact versioned execution improvement panel required')
    if lineage_retrieval_improvement and type(panel) is not LineageRetrievalImprovementPanel:
        raise ContractError('exact versioned lineage retrieval improvement panel required')
    if mechanism_improvement and type(panel) is not MechanismImprovementPanel:
        raise ContractError('exact versioned mechanism improvement panel required')
    if state_improvement and type(panel) is not StateImprovementPanel:
        raise ContractError('versioned state improvement panel required')
    if admission or exploration_scheduler or not lineage and not retrieval_review and not state_prediction and not state_retrieval and not state_exploration and not state_scheduling and not state_improvement and not mechanism_exploration and not mechanism_scheduling and not mechanism_improvement and not admission_prediction_exploration and not lineage_retrieval_improvement and not execution_improvement and not full_loo and not joint_train:
        designs = {'pair:M7+M8': ('M7','M8')} if exploration_scheduler else ADMISSION_DESIGNS if admission else {'pair:M4+M5': ('M4','M5')}
        if not panel.cells or panel.design != default_compatibility(panel.cells[0].runtime_arm.data()['baseline_digest']).conditional_factorial(designs[panel.obligation_id]):
            raise ContractError('process scoring design differs from default registered compatibility')
    return {"schema": "combination-scorer-process-panel-v1", "panel_digest": panel.digest, "panel": {
        "stage": panel.stage, "domain": panel.domain, "split_digest": panel.split_digest,
        "obligation_id": panel.obligation_id, "estimand": panel.estimand, "design": panel.design.data(),
        "package_bundle": panel.package_bundle.data(), "acceptance_criteria": panel.acceptance_criteria.data(),
        "cells": [cell.data() for cell in panel.cells], "required_benchmarks": list(panel.required_benchmarks),
        **({"training_provenance": panel.training_provenance.data()} if state_improvement or mechanism_improvement or lineage_retrieval_improvement or execution_improvement or full_loo or joint_train else {})}}


def parse_combination_panel(value: object, *, lineage: bool = False,
                            retrieval_review: bool = False, admission: bool = False, exploration_scheduler: bool = False,
                            state_prediction: bool = False, state_retrieval: bool = False, state_exploration: bool = False, state_scheduling: bool = False, state_improvement: bool = False, mechanism_exploration: bool = False, mechanism_scheduling: bool = False, mechanism_improvement: bool = False, admission_prediction_exploration: bool = False, lineage_retrieval_improvement: bool = False, execution_improvement: bool = False, full_loo: bool = False, joint_train: bool = False) -> CombinationPanel:
    if (not isinstance(value, Mapping) or set(value) != {"schema", "panel_digest", "panel"}
            or value["schema"] != "combination-scorer-process-panel-v1" or not isinstance(value["panel"], Mapping)):
        raise ContractError("combination scorer panel envelope is invalid")
    body = value["panel"]
    if set(body) != {"stage", "domain", "split_digest", "obligation_id", "estimand", "design", "package_bundle", "acceptance_criteria", "cells", "required_benchmarks"} | ({"training_provenance"} if state_improvement or mechanism_improvement or lineage_retrieval_improvement or execution_improvement or full_loo or joint_train else set()):
        raise ContractError("combination scorer panel fields are invalid")
    try:
        cells = tuple(PanelCell(row["coverage_id"], DataIdentity.parse(row["identity"]), row["replicate"],
            row["variant"], row["arm_id"], FrozenRecord.from_dict(row["runtime_arm"]), row["task_digest"],
            row["scenario_digest"], row["package_digest"], row["scorer_digest"]) for row in body["cells"])
        from research_loop.modular.state_improvement_panel import StateImprovementPanel
        from research_loop.modular.mechanism_improvement_panel import MechanismImprovementPanel
        from research_loop.modular.lineage_retrieval_improvement_panel import LineageRetrievalImprovementPanel
        from research_loop.modular.execution_improvement_panel import ExecutionImprovementPanel
        from research_loop.modular.full_loo_panel import FullLooPanel
        from research_loop.modular.joint_train_panel import JointTrainPanel
        cls = JointTrainPanel if joint_train else FullLooPanel if full_loo else ExecutionImprovementPanel if execution_improvement else LineageRetrievalImprovementPanel if lineage_retrieval_improvement else MechanismImprovementPanel if mechanism_improvement else StateImprovementPanel if state_improvement else CombinationPanel
        panel = cls(body["stage"], body["domain"], body["split_digest"], body["obligation_id"],
            body["estimand"], FrozenRecord.from_dict(body["design"]), FrozenRecord.from_dict(body["package_bundle"]),
            FrozenRecord.from_dict(body["acceptance_criteria"]), cells, tuple(body["required_benchmarks"]),
            **({"training_provenance": FrozenRecord.from_dict(body["training_provenance"])} if state_improvement or mechanism_improvement or lineage_retrieval_improvement or execution_improvement or full_loo or joint_train else {}))
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("combination scorer panel cannot be reconstructed") from exc
    if serialize_combination_panel(panel, lineage=lineage, retrieval_review=retrieval_review, admission=admission,
                                   exploration_scheduler=exploration_scheduler, state_prediction=state_prediction, state_retrieval=state_retrieval, state_exploration=state_exploration, state_scheduling=state_scheduling, state_improvement=state_improvement, mechanism_exploration=mechanism_exploration, mechanism_scheduling=mechanism_scheduling, mechanism_improvement=mechanism_improvement, admission_prediction_exploration=admission_prediction_exploration, lineage_retrieval_improvement=lineage_retrieval_improvement, execution_improvement=execution_improvement, full_loo=full_loo, joint_train=joint_train) != value:
        raise ContractError("combination scorer panel differs from its complete frozen serialization")
    return panel


def scorer_process_binding(*, panel: FrozenPanel | CombinationPanel, config: ScorerConfig,
                           task_handle_bindings: Mapping[str, str], execution_authority_keys: Mapping[str, bytes],
                           scorer_authority_keys: Mapping[str, bytes]) -> FrozenRecord:
    """Public configuration proof; contains key hashes, never keys or references."""
    if not isinstance(panel, (FrozenPanel, CombinationPanel)) or not isinstance(config, ScorerConfig):
        raise ContractError("scorer process binding requires a typed panel and rubric")
    expected = {digest(cell.identity.data()) for cell in panel.cells}
    if set(task_handle_bindings) != expected or any(not isinstance(v, str) or _digest(v, "handle binding") != v for v in task_handle_bindings.values()):
        raise ContractError("scorer process handle bindings differ from the panel")
    if (not execution_authority_keys or len(scorer_authority_keys) != 1
            or set(execution_authority_keys) & set(scorer_authority_keys)
            or any(not isinstance(key, bytes) or len(key) < 32 for key in (*execution_authority_keys.values(), *scorer_authority_keys.values()))
            or set(execution_authority_keys.values()) & set(scorer_authority_keys.values())):
        raise ContractError("scorer process authority binding is invalid")
    return FrozenRecord.from_dict({"schema": "scorer-process-binding-v1", "panel_digest": panel.digest,
        "panel_kind": "combination" if isinstance(panel, CombinationPanel) else "linked",
        "scorer_config_digest": config.digest, "task_handle_bindings": dict(task_handle_bindings),
        "execution_key_sha256": {name: _sha(key) for name, key in execution_authority_keys.items()},
        "scorer_key_sha256": {name: _sha(key) for name, key in scorer_authority_keys.items()}})


@dataclass(frozen=True)
class ScorerServerConfig:
    panel: FrozenPanel | CombinationPanel
    scorer: ScorerConfig
    store_root: Path
    manifest_sha256: str
    inventory_digest: str
    split_digest: str
    task_handles: Mapping[str, str]
    execution_keys: Mapping[str, bytes]
    scorer_authority: LinkedExecutionAuthority
    evaluator: Mapping[str, object]


def parse_server_config(value: object, *, lineage: bool = False) -> ScorerServerConfig:
    required = {"schema", "panel", "scorer_config", "scorer_config_digest", "train_reference_store", "task_handles", "execution_authority_key_files", "scorer_authority", "evaluator"}
    exploration_schema = 'exploration-scheduler-scorer-process-config-v1'
    admission_schema = 'admission-combination-scorer-process-config-v1'
    retrieval_schema = 'retrieval-review-scorer-process-config-v1'
    state_prediction_schema = 'state-prediction-scorer-process-config-v1'
    state_retrieval_schema = 'state-retrieval-scorer-process-config-v1'
    state_exploration_schema = 'state-exploration-scorer-process-config-v1'
    state_scheduling_schema = 'state-scheduling-scorer-process-config-v1'
    state_improvement_schema = 'state-improvement-scorer-process-config-v1'
    mechanism_exploration_schema = 'mechanism-exploration-scorer-process-config-v1'
    mechanism_scheduling_schema = 'mechanism-scheduling-scorer-process-config-v1'
    mechanism_improvement_schema = 'mechanism-improvement-scorer-process-config-v1'
    admission_prediction_exploration_schema = 'admission-prediction-exploration-scorer-process-config-v1'
    lineage_retrieval_improvement_schema = 'lineage-retrieval-improvement-scorer-process-config-v1'
    joint_train_schema = 'c5-common-train-scorer-process-config-v1'
    full_loo_schema = 'c4-full-loo-scorer-process-config-v1'
    execution_improvement_schema = 'execution-improvement-scorer-process-config-v1'
    if not isinstance(value, Mapping) or set(value) != required or value.get("schema") not in {_CONFIG_SCHEMA, _COMBINATION_CONFIG_SCHEMA, retrieval_schema, admission_schema, exploration_schema, state_prediction_schema, state_retrieval_schema, state_exploration_schema, state_scheduling_schema, state_improvement_schema, mechanism_exploration_schema, mechanism_scheduling_schema, mechanism_improvement_schema, admission_prediction_exploration_schema, lineage_retrieval_improvement_schema, execution_improvement_schema, full_loo_schema, joint_train_schema}:
        raise ContractError("scorer process configuration is invalid")
    panel = (parse_combination_panel(value["panel"], lineage=lineage,
                 retrieval_review=value['schema']==retrieval_schema, admission=value['schema']==admission_schema,
                 exploration_scheduler=value['schema']==exploration_schema, state_prediction=value['schema']==state_prediction_schema, state_retrieval=value['schema']==state_retrieval_schema, state_exploration=value['schema']==state_exploration_schema, state_scheduling=value['schema']==state_scheduling_schema, state_improvement=value['schema']==state_improvement_schema, mechanism_exploration=value['schema']==mechanism_exploration_schema, mechanism_scheduling=value['schema']==mechanism_scheduling_schema, mechanism_improvement=value['schema']==mechanism_improvement_schema, admission_prediction_exploration=value['schema']==admission_prediction_exploration_schema, lineage_retrieval_improvement=value['schema']==lineage_retrieval_improvement_schema, execution_improvement=value['schema']==execution_improvement_schema, full_loo=value['schema']==full_loo_schema, joint_train=value['schema']==joint_train_schema)
             if value["schema"] in {_COMBINATION_CONFIG_SCHEMA, retrieval_schema, admission_schema, exploration_schema, state_prediction_schema, state_retrieval_schema, state_exploration_schema, state_scheduling_schema, state_improvement_schema, mechanism_exploration_schema, mechanism_scheduling_schema, mechanism_improvement_schema, admission_prediction_exploration_schema, lineage_retrieval_improvement_schema, execution_improvement_schema, full_loo_schema, joint_train_schema}
             else parse_frozen_panel(value["panel"]))
    if panel.domain != "train" or any(cell.identity.domain != "train" for cell in panel.cells):
        raise ContractError("scorer process is train-only")
    scorer = ScorerConfig(FrozenRecord.from_dict(value["scorer_config"]))
    if scorer.digest != _digest(value["scorer_config_digest"], "scorer config digest"):
        raise ContractError("scorer process configuration digest mismatch")
    if any(cell.scorer_digest != scorer.digest or cell.identity.benchmark not in scorer.benchmarks for cell in panel.cells):
        raise ContractError("panel cell scorer configuration drift")
    store = value["train_reference_store"]
    if not isinstance(store, Mapping) or set(store) != {"root", "manifest_sha256", "inventory_digest", "split_digest"}:
        raise ContractError("train reference store configuration is invalid")
    store_root = _absolute(store["root"], "train reference store root")
    manifest_sha256 = _digest(store["manifest_sha256"], "train reference manifest")
    # The reference-store contract binds these exact custody identifiers.  Its
    # synthetic integration fixtures deliberately use readable identifiers,
    # so only the manifest itself is required to be a sha256 pin here.
    inventory_digest = _text(store["inventory_digest"], "train inventory")
    split_digest = _text(store["split_digest"], "train split")
    if panel.split_digest != split_digest or any(cell.identity.dataset_version != inventory_digest or cell.identity.split_id != split_digest for cell in panel.cells):
        raise ContractError("panel identity differs from the train reference store")
    supplied_handles = value["task_handles"]
    if not isinstance(supplied_handles, Mapping):
        raise ContractError("task handle map is invalid")
    handles = {str(identity): handle for identity, handle in supplied_handles.items()}
    expected_identities = {digest(cell.identity.data()) for cell in panel.cells}
    if set(handles) != expected_identities or any(not isinstance(handle, str) or not handle for handle in handles.values()):
        raise ContractError("task handle map differs from the frozen panel")
    files = value["execution_authority_key_files"]
    if not isinstance(files, Mapping) or not files:
        raise ContractError("execution authority key files are invalid")
    execution_keys = {str(authority): _key(_absolute(path, "execution authority key file"), "execution authority key") for authority, path in files.items()}
    if any(not authority for authority in execution_keys):
        raise ContractError("execution authority id is invalid")
    scorer_spec = value["scorer_authority"]
    if not isinstance(scorer_spec, Mapping) or set(scorer_spec) != {"id", "key_file"} or not isinstance(scorer_spec["id"], str):
        raise ContractError("scorer authority configuration is invalid")
    scorer_authority = LinkedExecutionAuthority(scorer_spec["id"], _key(_absolute(scorer_spec["key_file"], "scorer authority key file"), "scorer authority key"))
    if scorer_authority.authority_id in execution_keys or any(key == scorer_authority.key for key in execution_keys.values()):
        raise ContractError("execution and scorer authorities must be distinct")
    if not isinstance(value["evaluator"], Mapping):
        raise ContractError("evaluator configuration is invalid")
    return ScorerServerConfig(panel, scorer, store_root, manifest_sha256, inventory_digest, split_digest, handles, execution_keys, scorer_authority, dict(value["evaluator"]))


def _headless_evaluator(spec: Mapping[str, object], *, rubric_mode: str):
    """Explicit private rubric transport; legacy Codex declarations stay distinct."""
    from evaluation.modular.headless_evaluator_model_port import GrokHeadlessEvaluatorModelPort
    required = {"provider_kind", "executable", "work_root", "private_home", "private_profile", "public_cwd",
                "frozen_files", "evaluator_id", "evaluator_version", "model", "effort", "max_calls",
                "max_tokens", "timeout_seconds", "account_read_recovery"}
    if (set(spec) != required or spec.get("provider_kind") != "grok-headless-frozen-evaluator-v1"
            or spec.get("model") != "grok-4.6" or spec.get("effort") != "low"
            or type(spec.get("timeout_seconds")) is not int or spec["timeout_seconds"] != 60
            or not isinstance(spec.get("frozen_files"), Mapping) or not spec["frozen_files"]):
        raise ContractError("production headless evaluator configuration is invalid")
    for name in ("max_calls", "max_tokens"):
        if type(spec[name]) is not int or spec[name] < 1:
            raise ContractError("production headless evaluator budget is invalid")
    for name in ("evaluator_id", "evaluator_version"):
        _text(spec[name], "headless " + name)
    pins = {str(_absolute(path, "headless frozen source")): _digest(value, "headless frozen source")
            for path, value in spec["frozen_files"].items()}
    return GrokHeadlessEvaluatorModelPort(
        executable=_absolute(spec["executable"], "headless executable"),
        work_root=_absolute(spec["work_root"], "headless work root"),
        private_home=_absolute(spec["private_home"], "headless private home"),
        private_profile=_absolute(spec["private_profile"], "headless private profile"),
        public_cwd=_absolute(spec["public_cwd"], "headless public cwd"), frozen_files=pins,
        evaluator_id=spec["evaluator_id"], evaluator_version=spec["evaluator_version"], rubric_mode=rubric_mode,
        max_calls=spec["max_calls"], max_tokens=spec["max_tokens"], timeout_seconds=spec["timeout_seconds"],
        account_read_recovery=spec["account_read_recovery"])


def _production_evaluator(spec: Mapping[str, object], *, rubric_mode: str = "primary_v1"):
    if spec.get("provider_kind") == "grok-headless-frozen-evaluator-v1":
        return _headless_evaluator(spec, rubric_mode=rubric_mode)
    required = {"executable", "work_root", "evaluator_id", "evaluator_version", "model", "effort", "max_calls", "max_tokens", "timeout_seconds", "frozen_base_context"}
    if set(spec) != required or not isinstance(spec["frozen_base_context"], Mapping) or set(spec["frozen_base_context"]) != {"source", "sha256"}:
        raise ContractError("production evaluator configuration is invalid")
    context = spec["frozen_base_context"]
    policy = FrozenBaseContextPolicy(_absolute(context["source"], "frozen context policy"), _digest(context["sha256"], "frozen context policy"))
    if not all(isinstance(spec[name], str) and spec[name] for name in ("executable", "evaluator_id", "evaluator_version", "model", "effort")):
        raise ContractError("production evaluator identity is invalid")
    if type(spec["max_calls"]) is not int or type(spec["max_tokens"]) is not int or type(spec["timeout_seconds"]) is not int:
        raise ContractError("production evaluator budget is invalid")
    return CodexEvaluatorModelPort(_absolute(spec["executable"], "evaluator executable"), _absolute(spec["work_root"], "evaluator work root"),
        evaluator_id=spec["evaluator_id"], evaluator_version=spec["evaluator_version"], rubric_mode=rubric_mode, model=spec["model"], effort=spec["effort"],
        max_calls=spec["max_calls"], max_tokens=spec["max_tokens"], timeout_seconds=spec["timeout_seconds"], frozen_base_context=policy)


def build_service(config: ScorerServerConfig, *, evaluator: Callable[[FrozenRecord], FrozenRecord] | None = None) -> LinkedAdaptedScoringService | CombinationAdaptedScoringService:
    """Load and verify the full train store before an evaluator can be invoked."""
    resolver = FrozenTrainReferenceResolver(config.store_root, manifest_sha256=config.manifest_sha256,
        inventory_digest=config.inventory_digest, split_digest=config.split_digest)
    # Check every frozen identity/handle now, rather than discovering a store
    # substitution after a model call for the first matching cell.
    for identity in {cell.identity for cell in config.panel.cells}:
        handle = config.task_handles[digest(identity.data())]
        reference = resolver(handle, identity.benchmark).data()
        if reference.get("identity_digest") != digest(identity.data()):
            raise ContractError("frozen train store identity differs from configured handle")
    model = evaluator if evaluator is not None else _production_evaluator(config.evaluator)
    endpoint = FrozenBenchmarkRubricEndpoint(resolver=resolver, evaluator=model,
        evaluator_id=config.scorer.record.data()["evaluator_id"], evaluator_version=config.scorer.record.data()["version"])
    service_type = CombinationAdaptedScoringService if isinstance(config.panel, CombinationPanel) else LinkedAdaptedScoringService
    return service_type(config=config.scorer, evaluator=FrozenRubricTransport(endpoint),
        execution_authority_keys=config.execution_keys, task_handles=config.task_handles, scorer_authority=config.scorer_authority)


def _append(path: Path, entry: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical(dict(entry)).encode("utf-8") + b"\n"
    with path.open("ab") as stream:
        stream.write(line); stream.flush(); os.fsync(stream.fileno())


def _journal(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    states: dict[str, dict[str, object]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("schema") != _JOURNAL_SCHEMA or set(row) - {"schema", "cell_key", "request_id", "request_digest", "status", "receipt"}:
                raise ValueError("invalid journal row")
            key = canonical(row["cell_key"])
            if row["status"] == "succeeded":
                FrozenRecord.from_dict(row["receipt"])
            elif row["status"] not in {"reserved", "unknown"} or "receipt" in row:
                raise ValueError("invalid journal state")
            if key in states and states[key]["status"] == "succeeded":
                raise ValueError("journal has repeated terminal cell")
            states[key] = row
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ContractError("scorer process journal is not safely recoverable") from exc
    return states


def _request(value: object, panel: FrozenPanel) -> tuple[str, tuple[str, ...], FrozenRecord, str]:
    required = {"schema", "request_id", "panel_digest", "cell_key", "linked_input", "request_digest"}
    if not isinstance(value, Mapping) or set(value) != required or value.get("schema") != _REQUEST_SCHEMA:
        raise ContractError("scorer process request is invalid")
    request_id = value["request_id"]
    if not isinstance(request_id, str) or not request_id:
        raise ContractError("scorer process request id is invalid")
    if value["panel_digest"] != panel.digest or not isinstance(value["cell_key"], list) or len(value["cell_key"]) != 7 or any(not isinstance(item, str) for item in value["cell_key"]):
        raise ContractError("scorer process request cell is invalid")
    cell_key = tuple(value["cell_key"])
    if cell_key not in {cell.key for cell in panel.cells}:
        raise ContractError("scorer process request cell is not predeclared")
    linked = FrozenRecord.from_dict(value["linked_input"])
    material = {"request_id": request_id, "panel_digest": panel.digest, "cell_key": list(cell_key), "linked_input": linked.data()}
    request_digest = _sha(canonical(material))
    if value["request_digest"] != request_digest:
        raise ContractError("scorer process request digest mismatch")
    return request_id, cell_key, linked, request_digest


class ScorerWorker:
    def __init__(self, service: LinkedAdaptedScoringService, panel: FrozenPanel, journal_path: Path):
        self.service, self.panel, self.journal_path = service, panel, journal_path
        self.states = _journal(journal_path)
        self.cells = {cell.key: cell for cell in panel.cells}

    def respond(self, value: object) -> dict[str, object]:
        if isinstance(value, Mapping) and value.get("schema") == "scorer-process-binding-request-v1":
            if set(value) != {"schema", "nonce"} or not isinstance(value["nonce"], str) or not value["nonce"]:
                raise ContractError("scorer binding request is malformed")
            binding = scorer_process_binding(panel=self.panel, config=self.service.config,
                task_handle_bindings={key: _sha(handle) for key, handle in self.service._handles.items()},
                execution_authority_keys=self.service._execution_keys,
                scorer_authority_keys={self.service._authority.authority_id: self.service._authority.key})
            if hasattr(self.service, 'lineage_reference_binding'):
                binding = FrozenRecord.from_dict({**binding.data(), 'lineage_references': self.service.lineage_reference_binding})
            return {"schema": "scorer-process-binding-response-v1", "nonce": value["nonce"], "binding": binding.data()}
        request_id, key, linked, request_digest = _request(value, self.panel)
        state = self.states.get(canonical(list(key)))
        base = {"schema": _RESPONSE_SCHEMA, "request_id": request_id, "request_digest": request_digest, "cell_key": list(key)}
        if state is not None:
            if state["request_digest"] != request_digest:
                return base | {"status": "rejected"}
            if state["status"] == "succeeded":
                return base | {"status": "succeeded", "receipt": state["receipt"]}
            return base | {"status": "unknown"}
        reservation = {"schema": _JOURNAL_SCHEMA, "cell_key": list(key), "request_id": request_id,
                       "request_digest": request_digest, "status": "reserved"}
        _append(self.journal_path, reservation); self.states[canonical(list(key))] = reservation
        try:
            if hasattr(self.service, 'score_lineage'):
                receipt = self.service.score_lineage(panel=self.panel, cell=self.cells[key], score_input=linked)
            elif isinstance(self.panel, CombinationPanel):
                receipt = self.service.score_combination(panel=self.panel, cell=self.cells[key], score_input=linked)
            else:
                receipt = self.service.score_linked(panel=self.panel, cell=self.cells[key], linked_input=linked)
        except Exception:
            unknown = reservation | {"status": "unknown"}
            _append(self.journal_path, unknown); self.states[canonical(list(key))] = unknown
            return base | {"status": "unknown"}
        success = reservation | {"status": "succeeded", "receipt": receipt.receipt.data()}
        _append(self.journal_path, success); self.states[canonical(list(key))] = success
        return base | {"status": "succeeded", "receipt": receipt.receipt.data()}


def serve(worker: ScorerWorker, input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> int:
    # The signed JSON wire format is UTF-8. A client-side encoding argument
    # does not configure the child's stdin/stdout on Windows (often GBK).
    # Preserve explicit caller-owned test streams; configure only real stdio.
    if input_stream is None:
        input_stream = sys.stdin
        input_stream.reconfigure(encoding="utf-8", errors="strict")
    if output_stream is None:
        output_stream = sys.stdout
        output_stream.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    for line in input_stream:
        try:
            response = worker.respond(json.loads(line))
        except Exception:
            response = {"schema": _RESPONSE_SCHEMA, "status": "rejected"}
        output_stream.write(canonical(response) + "\n"); output_stream.flush()
    return 0


class LinkedScorerProcessClient:
    """Sequential stdio client with a local no-retry reservation journal."""
    def __init__(self, *, panel: FrozenPanel, command: list[str], journal_path: Path,
                 environment: Mapping[str, str] | None = None, response_timeout_seconds: int = 240):
        if not isinstance(panel, (FrozenPanel, CombinationPanel)) or not command or any(not isinstance(item, str) or not item for item in command):
            raise ContractError("scorer process client needs a panel and command")
        if environment is not None and (not isinstance(environment, Mapping)
                or any(not isinstance(key, str) or not isinstance(value, str) for key, value in environment.items())):
            raise ContractError("scorer process environment must contain string keys and values")
        if type(response_timeout_seconds) is not int or response_timeout_seconds < 1:
            raise ContractError("scorer process response timeout must be positive")
        self.panel, self.cells, self.journal_path = panel, {cell.key: cell for cell in panel.cells}, journal_path
        self.response_timeout_seconds = response_timeout_seconds
        # A malformed local journal is an unknown prior reservation.  Reject it
        # before process creation, so it cannot leave an unused scorer worker.
        self.states = _journal(journal_path)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", creationflags=flags, env=dict(environment) if environment is not None else None)
        if self.process.stdin is None or self.process.stdout is None:
            raise ContractError("scorer process stdio is unavailable")
        self.input, self.output = self.process.stdin, self.process.stdout

    def close(self) -> None:
        if not self.input.closed:
            try:
                self.input.close()
            except OSError:
                # A failed worker may already have closed its inherited pipe;
                # still reap it so subsequent runs cannot inherit it.
                pass
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self._stop_unknown_worker()

    def _stop_unknown_worker(self) -> None:
        """Do not let a timed-out scorer continue an unacknowledged cell."""
        try:
            if not self.input.closed:
                self.input.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=20)

    def _readline_bounded(self) -> str:
        result: Queue[object] = Queue(maxsize=1)
        def read() -> None:
            try:
                result.put(self.output.readline())
            except BaseException as exc:  # Pipe errors are normalized below.
                result.put(exc)
        Thread(target=read, daemon=True).start()
        try:
            value = result.get(timeout=self.response_timeout_seconds)
        except Empty as exc:
            self._stop_unknown_worker()
            raise ContractError("scorer process response timed out") from exc
        if isinstance(value, BaseException):
            raise ContractError("scorer process response is unavailable") from value
        return value if isinstance(value, str) else ""

    def submit(self, *, cell_key: tuple[str, ...], linked_input: FrozenRecord) -> ScientificScorerReceipt:
        if cell_key not in self.cells or not isinstance(linked_input, FrozenRecord):
            raise ContractError("scorer client input is not a frozen panel cell")
        state = self.states.get(canonical(list(cell_key)))
        if state is not None:
            if state["status"] == "succeeded":
                material = {"request_id": state["request_id"], "panel_digest": self.panel.digest,
                    "cell_key": list(cell_key), "linked_input": linked_input.data()}
                if _sha(canonical(material)) != state["request_digest"]:
                    raise ContractError("scorer client repeat input differs from completed request")
                return ScientificScorerReceipt(cell_key, FrozenRecord.from_dict(state["receipt"]))
            raise ContractError("scorer client has an unresolved prior reservation")
        request_id = uuid.uuid4().hex
        material = {"request_id": request_id, "panel_digest": self.panel.digest, "cell_key": list(cell_key), "linked_input": linked_input.data()}
        request_digest = _sha(canonical(material))
        reservation = {"schema": _JOURNAL_SCHEMA, "cell_key": list(cell_key), "request_id": request_id,
                       "request_digest": request_digest, "status": "reserved"}
        _append(self.journal_path, reservation); self.states[canonical(list(cell_key))] = reservation
        request = {"schema": _REQUEST_SCHEMA, **material, "request_digest": request_digest}
        try:
            self.input.write(canonical(request) + "\n"); self.input.flush()
            line = self._readline_bounded()
            response = json.loads(line) if line else None
            required = {"schema", "request_id", "request_digest", "cell_key", "status", "receipt"}
            if (not isinstance(response, dict) or set(response) != required or response.get("schema") != _RESPONSE_SCHEMA
                    or response.get("request_id") != request_id or response.get("request_digest") != request_digest
                    or response.get("cell_key") != list(cell_key) or response.get("status") != "succeeded"):
                raise ContractError("scorer process did not return a bound receipt")
            receipt = FrozenRecord.from_dict(response["receipt"])
        except Exception as exc:
            unknown = reservation | {"status": "unknown"}
            _append(self.journal_path, unknown); self.states[canonical(list(cell_key))] = unknown
            if not isinstance(exc, ContractError) or "timed out" in str(exc) or "unavailable" in str(exc):
                self._stop_unknown_worker()
            if isinstance(exc, ContractError):
                raise
            raise ContractError("scorer process result is unknown") from exc
        success = reservation | {"status": "succeeded", "receipt": receipt.data()}
        _append(self.journal_path, success); self.states[canonical(list(cell_key))] = success
        return ScientificScorerReceipt(cell_key, receipt)


class CombinationScorerProcessClient(LinkedScorerProcessClient):
    """Combination adapter over the same UTF-8, no-retry cell transaction wire.

    The legacy wire field is named ``linked_input``; its content remains the
    independently verified, signed combination input. The child selects the
    scorer by its frozen panel type. A startup handshake compares every public
    configuration binding before this object can reach the train controller.
    """
    def __init__(self, *, panel: CombinationPanel, config: ScorerConfig, command: list[str], journal_path: Path,
                 task_handle_bindings: Mapping[str, str], execution_authority_keys: Mapping[str, bytes],
                 scorer_authority_keys: Mapping[str, bytes], environment: Mapping[str, str] | None = None,
                 response_timeout_seconds: int = 240, retrieval_review: bool = False, admission: bool = False,
                 exploration_scheduler: bool = False, state_prediction: bool = False, state_retrieval: bool = False, state_exploration: bool = False, state_scheduling: bool = False, state_improvement: bool = False, mechanism_exploration: bool = False, mechanism_scheduling: bool = False, mechanism_improvement: bool = False, admission_prediction_exploration: bool = False, lineage_retrieval_improvement: bool = False, execution_improvement: bool = False, full_loo: bool = False, joint_train: bool = False):
        serialize_combination_panel(panel, retrieval_review=retrieval_review, admission=admission,
                                    exploration_scheduler=exploration_scheduler, state_prediction=state_prediction, state_retrieval=state_retrieval, state_exploration=state_exploration, state_scheduling=state_scheduling, state_improvement=state_improvement, mechanism_exploration=mechanism_exploration, mechanism_scheduling=mechanism_scheduling, mechanism_improvement=mechanism_improvement, admission_prediction_exploration=admission_prediction_exploration, lineage_retrieval_improvement=lineage_retrieval_improvement, execution_improvement=execution_improvement, full_loo=full_loo, joint_train=joint_train)
        expected = scorer_process_binding(panel=panel, config=config, task_handle_bindings=task_handle_bindings,
            execution_authority_keys=execution_authority_keys, scorer_authority_keys=scorer_authority_keys)
        self.config, self.state_prediction, self.state_retrieval = config, state_prediction, state_retrieval
        self.state_exploration = state_exploration
        self.state_scheduling = state_scheduling
        self.state_improvement = state_improvement
        self.mechanism_exploration = mechanism_exploration
        self.mechanism_scheduling = mechanism_scheduling
        self.mechanism_improvement = mechanism_improvement
        self.admission_prediction_exploration = admission_prediction_exploration
        self.lineage_retrieval_improvement = lineage_retrieval_improvement
        self.full_loo = full_loo
        self.joint_train = joint_train
        self.execution_improvement = execution_improvement
        super().__init__(panel=panel, command=command, journal_path=journal_path,
                         environment=environment, response_timeout_seconds=response_timeout_seconds)
        try:
            nonce = uuid.uuid4().hex
            self.input.write(canonical({"schema": "scorer-process-binding-request-v1", "nonce": nonce}) + "\n")
            self.input.flush()
            response = json.loads(self._readline_bounded())
            if response != {"schema": "scorer-process-binding-response-v1", "nonce": nonce, "binding": expected.data()}:
                raise ContractError("combination scorer startup binding differs from frozen configuration")
            self.binding = expected
        except Exception as exc:
            self._stop_unknown_worker()
            if isinstance(exc, ContractError):
                raise
            raise ContractError("combination scorer startup did not return its bound configuration") from exc

    def assert_configuration(self, *, config: ScorerConfig, task_handle_bindings: Mapping[str, str],
                             execution_authority_keys: Mapping[str, bytes], scorer_authority_keys: Mapping[str, bytes]) -> None:
        expected = scorer_process_binding(panel=self.panel, config=config, task_handle_bindings=task_handle_bindings,
            execution_authority_keys=execution_authority_keys, scorer_authority_keys=scorer_authority_keys)
        if self.config != config or self.binding != expected or self.process.poll() is not None:
            raise ContractError("combination scorer configuration or worker state drift")

    def score_combination(self, *, panel: CombinationPanel, cell: PanelCell, score_input: FrozenRecord) -> ScientificScorerReceipt:
        if panel != self.panel or self.cells.get(cell.key) != cell:
            raise ContractError("combination scorer cell differs from the frozen process panel")
        return super().submit(cell_key=cell.key, linked_input=score_input)


def _load(path: Path, expected_sha256: str) -> ScorerServerConfig:
    try:
        raw = path.read_bytes()
        if _sha(raw) != _digest(expected_sha256, "configuration sha256"):
            raise ContractError("scorer process configuration hash mismatch")
        return parse_server_config(json.loads(raw.decode("utf-8")))
    except ContractError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise ContractError("scorer process configuration cannot be loaded") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="train-only linked scorer worker")
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--journal", required=True)
    args = parser.parse_args(argv)
    config = _load(_absolute(args.config, "config"), args.config_sha256)
    worker = ScorerWorker(build_service(config), config.panel, _absolute(args.journal, "journal"))
    return serve(worker)


if __name__ == "__main__":
    raise SystemExit(main())
