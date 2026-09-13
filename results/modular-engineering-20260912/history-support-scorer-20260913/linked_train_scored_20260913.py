"""Freeze/run a complete Q3.1 training grid with separate-process adapted scoring."""
import argparse
import hashlib
import importlib.util
import json
import secrets
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from evaluation.modular.custody import CustodyStore
from evaluation.modular.linked_scoring import LinkedExecutionAuthority, issue_linked_score_input
from evaluation.modular.scorer_process import LinkedScorerProcessClient, serialize_frozen_panel
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint, ScorerConfig
from research_loop.modular.__main__ import programme_plan
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.model_port import CodexModelPort, FrozenBaseContextPolicy
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.modular.train_selection import FrozenTrainSelectionRule, measure_and_select_train
from research_loop.ontology import canonical

ROOT = Path(r"E:\_ryanDev\AI\research-loop-modular\work\linked-train-scored-20260913-01")
PRIVATE = Path(r"E:\_ryanDev\AI\research-loop-modular\custody-private\linked-scorer-runtime-20260913-01")
REFERENCES = Path(r"E:\_ryanDev\AI\research-loop-modular\work\train-reference-deployment-20260913-01")
STORE = Path(r"E:\_ryanDev\AI\research-loop-modular\custody-private\train-reference-store-20260913-01")
ISOLATION = Path(r"E:\_ryanDev\AI\research-loop-modular\work\q31-isolated-context")
POLICY = Path(r"E:\_ryanDev\AI\research-loop-modular\work\linked-train-context-20260913-01\REVIEWED-POLICY.json")
POLICY_SHA = "16f83e4c8cd78cb024fffcc6949090caeba939a56b1037e58264a57ed03da89b"
CUSTODY = Path(r"E:\_ryanDev\AI\research-loop-modular\benchmarks\work\custody-live-20260912.json")
CUSTODY_SHA = "933f158b947a0761ed297ea7cb713d816c2385e58f4d1df37dc7669071c9e96f"
SNAPSHOT = Path(r"E:\_ryanDev\AI\research-loop-benchmark-20260912")
EXECUTOR = "linked-train-executor-20260913-01"
SCORER = "linked-train-scorer-20260913-01"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(value))


def environment():
    spec = importlib.util.spec_from_file_location("linked_child_environment", ISOLATION / "context_environment_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.child_environment()


def source_commit():
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=SOURCE, text=True).strip():
        raise RuntimeError("Freeze tracked source before preparing or running this experiment")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()


def worker_command(preflight):
    return [sys.executable, "-m", "evaluation.modular.scorer_process", "--config", str(PRIVATE / "server-config.json"),
        "--config-sha256", preflight["server_config_sha256"], "--journal", str(PRIVATE / "server.jsonl")]


def probe():
    """Initialize the production worker and close stdin without a scoring request."""
    preflight = read(ROOT / "controls/preflight.json")
    assert source_commit() == preflight["source_commit"] and sha(CUSTODY) == CUSTODY_SHA
    if (ROOT / "controls/worker-probe.json").exists():
        raise RuntimeError("Startup probe is immutable")
    result = subprocess.run(worker_command(preflight), cwd=SOURCE, input="", capture_output=True,
        text=True, encoding="utf-8", env=environment(), timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (PRIVATE / "worker-probe.stderr.txt").write_text(result.stderr, encoding="utf-8")
    ledger_path = PRIVATE / "evaluator-model/ledger.json"
    ledger = read(ledger_path) if ledger_path.is_file() else None
    receipt = {"schema": "linked-scorer-startup-probe-v1", "source_commit": preflight["source_commit"],
        "server_config_sha256": preflight["server_config_sha256"], "exit_code": result.returncode,
        "stdout_empty": result.stdout == "", "stderr_sha256": sha(PRIVATE / "worker-probe.stderr.txt"),
        "evaluator_call_reservations": len(ledger["calls"]) if ledger else None,
        "evaluator_tokens": ledger["tokens"] if ledger else None,
        "validation_items": 0, "scientific_validity": "not_measured"}
    write(ROOT / "controls/worker-probe.json", receipt)
    print(canonical(receipt), flush=True)
    assert result.returncode == 0 and receipt["stdout_empty"] and ledger and not ledger["calls"] and ledger["tokens"] == 0


def prepare():
    if ROOT.exists() or PRIVATE.exists():
        raise RuntimeError("Attempt paths already exist; never overwrite or silently restart")
    assert sha(CUSTODY) == CUSTODY_SHA
    policy = FrozenBaseContextPolicy(POLICY, POLICY_SHA).data()
    publication = read(REFERENCES / "publication.json")
    assert sha(REFERENCES / "publication.json") == "dcb2c224f9e730f92ffd9fd9e4becd9cf4b8d1214dfef144aef8fee4ee893974"
    tasks = []
    for benchmark in ("blade", "discoverybench"):
        paths = list((REFERENCES / "public" / benchmark).glob("*/public.json"))
        assert len(paths) == 1
        envelope = read(paths[0])
        identity = DataIdentity.parse(envelope["task"]["identity"])
        identity.require_train()
        task = PublicTask.create(identity, envelope["task"]["payload"])
        assert task.content_hash == envelope["receipt"]["packet_hash"]
        assert sha(paths[0].parent / "data.csv") == envelope["receipt"]["csv_sha256"]
        tasks.append(task)
    source = source_commit()
    baseline = hashlib.sha256(("linked-train-scored-v1:" + source).encode()).hexdigest()
    control = FrozenRecord.from_dict(programme_plan(baseline).data()["P0_control_source_lock"])
    grids = obligation_grids(("Q3.1",), baseline_digest=baseline, p0_control=control)
    arms = executable_arms(grids["Q3.1"])
    baseline_arm = next(name for name, arm in arms.items() if not arm.data()["enabled"])
    rule = FrozenTrainSelectionRule.create(coverage_id="Q3.1", baseline_arm=baseline_arm,
        tie_break_order=[baseline_arm, *sorted(set(arms) - {baseline_arm})],
        minimum_mean_improvement=0.0, maximum_benchmark_regression=0.0)
    scorer = ScorerConfig.create(benchmark="core_pair", evaluator_id="frozen-rubric-luna-train-v1",
        rubric_digest=FrozenBenchmarkRubricEndpoint.rubric_digest(), version="1")
    package = CandidatePackage.create(parent_digest=None,
        manifest=TrainingManifest.freeze([task.identity for task in tasks]),
        changes={"prompt": {"instructions": "Use only the current public task and supplied material. Produce operational competing predictions, execute the public-data analysis, and answer from its observations. No execution alone proves scientific validity."}}, search_cost=0)
    packages = {arm.content_hash: package for arm in arms.values()}
    prior = read(ISOLATION.parent / "q31-live-20260913-isolated/controls/config.json")
    schemas = prior["schemas"]
    schemas["scenario"]["properties"]["branches"].update(minItems=3, maxItems=3)
    schemas["analysis_program"] = {"type": "object", "properties": {"analysis": {"type": "string"}, "program": {"type": "string"}}, "required": ["analysis", "program"], "additionalProperties": False}
    schemas["final_answer"] = schemas["final"]
    criteria = {"scope": "training_adapted_only", "required_cells": 12, "allowed_failures": 0,
        "scientific_promotion": False, "train_adapted_selection": rule.record.data(),
        "mechanism_effect": "not_measured", "matched_tokens": "not_claimed"}
    body = {"schema": "train-panel-controller-v1", "engineering_scope": "train_only_panel_engineering",
        "execution_mode": "linked_benchmark_solve", "stage": "linked-train-scored-20260913-01", "scope_ids": ["Q3.1"],
        "item_ids": [f"{task.identity.benchmark}:{task.identity.task_id}" for task in tasks],
        "evidence_by_task": {task.content_hash: {"observations": [], "scope": "Only exported public task and CSV are supplied; no executed observation exists before this run."} for task in tasks},
        "budget": {"model_calls_per_cell": 4, "execution_limit": 1, "matched_tokens": "not_claimed"},
        "baseline_digest": baseline, "p0_control": control.data(),
        "packages_by_arm": {key: value.record.data() for key, value in packages.items()},
        "scorer": scorer.record.data(), "acceptance_criteria": criteria, "replicates": ["r1"],
        "model": "gpt-5.6-luna", "effort": "low", "max_calls": 48, "max_tokens": 750000, "schemas": schemas}
    config = FrozenTrainControllerConfig(FrozenRecord.from_dict(body))
    compiled = compile_train_panel(stage=body["stage"], scope_ids=("Q3.1",), tasks=tasks,
        evidence_by_task={key: FrozenRecord.from_dict(value) for key, value in body["evidence_by_task"].items()},
        budget=FrozenRecord.from_dict(body["budget"]), baseline_digest=baseline, p0_control=control,
        packages_by_arm=packages, scorer=scorer.record, acceptance_criteria=FrozenRecord.from_dict(criteria), replicates=("r1",))
    assert len(compiled.panel.cells) == 12
    ROOT.mkdir(parents=True); (ROOT / "controls").mkdir(); PRIVATE.mkdir(parents=True)
    for name in (EXECUTOR, SCORER, "unused-audit-a", "unused-audit-b"):
        (PRIVATE / (name + ".key")).write_bytes(secrets.token_bytes(32))
    server = {"schema": "linked-scorer-process-config-v1", "panel": serialize_frozen_panel(compiled.panel),
        "scorer_config": scorer.record.data(), "scorer_config_digest": scorer.digest,
        "train_reference_store": {"root": str(STORE), **{key: publication[key] for key in ("manifest_sha256", "inventory_digest", "split_digest")}},
        "task_handles": publication["task_handles"], "execution_authority_key_files": {EXECUTOR: str(PRIVATE / (EXECUTOR + ".key"))},
        "scorer_authority": {"id": SCORER, "key_file": str(PRIVATE / (SCORER + ".key"))},
        "evaluator": {"executable": policy["binding"]["cli_path"], "work_root": str(PRIVATE / "evaluator-model"),
            "evaluator_id": scorer.record.data()["evaluator_id"], "evaluator_version": "1", "model": "gpt-5.6-luna", "effort": "low",
            "max_calls": 12, "max_tokens": 1000000, "timeout_seconds": 240,
            "frozen_base_context": {"source": str(POLICY), "sha256": POLICY_SHA}}}
    write(ROOT / "controls/controller.json", config.data())
    write(PRIVATE / "server-config.json", server)
    write(ROOT / "controls/preflight.json", {"source_commit": source, "config_sha256": sha(ROOT / "controls/controller.json"),
        "server_config_sha256": sha(PRIVATE / "server-config.json"), "panel_digest": compiled.panel.digest,
        "scope_ids": ["Q3.1"], "training_items": body["item_ids"], "cells": 12,
        "solver_call_cap": 48, "solver_token_cap": 750000, "evaluator_call_cap": 12, "evaluator_token_cap": 1000000,
        "policy_sha256": POLICY_SHA, "custody_sha256": CUSTODY_SHA, "paid_calls": 0,
        "calibration": "not_measured", "OS_isolation": "not_established", "validation_items": 0})
    print(canonical(read(ROOT / "controls/preflight.json")), flush=True)


def run():
    preflight = read(ROOT / "controls/preflight.json")
    assert source_commit() == preflight["source_commit"] and sha(CUSTODY) == CUSTODY_SHA
    assert sha(PRIVATE / "server-config.json") == preflight["server_config_sha256"]
    probe_receipt = read(ROOT / "controls/worker-probe.json")
    assert probe_receipt["exit_code"] == 0 and probe_receipt["stdout_empty"]
    assert probe_receipt["server_config_sha256"] == preflight["server_config_sha256"]
    assert probe_receipt["evaluator_call_reservations"] == probe_receipt["evaluator_tokens"] == 0
    if (ROOT / "run").exists() or (ROOT / "model").exists():
        raise RuntimeError("Existing execution attempt must be inspected, never restarted")
    config = FrozenTrainControllerConfig.from_path(ROOT / "controls/controller.json", preflight["config_sha256"])
    data = config.data(); policy = FrozenBaseContextPolicy(POLICY, POLICY_SHA)
    model = CodexModelPort(policy.data()["binding"]["cli_path"], ROOT / "model", model=data["model"], effort=data["effort"],
        max_calls=data["max_calls"], max_tokens=data["max_tokens"], schema_by_slot=data["schemas"],
        timeout_seconds=240, frozen_base_context=policy, environment=environment())
    model._require_frozen_context()
    print(canonical({"stage": "fresh_context_matched", "paid_calls": 0}), flush=True)
    verifier = AuditVerifier({name: (PRIVATE / (name + ".key")).read_bytes() for name in ("unused-audit-a", "unused-audit-b")})
    result = run_train_panel(config, custody=CustodyStore(CUSTODY), snapshot_root=SNAPSHOT,
        export_root=ROOT / "export", run_root=ROOT / "run", model=model, audit_verifier=verifier)
    assert result.compiled.panel.digest == preflight["panel_digest"]
    execution_key = (PRIVATE / (EXECUTOR + ".key")).read_bytes()
    authority = LinkedExecutionAuthority(EXECUTOR, execution_key)
    command = worker_command(preflight)
    client = LinkedScorerProcessClient(panel=result.compiled.panel, command=command,
        journal_path=ROOT / "scorer-client.jsonl", environment=environment(), response_timeout_seconds=360)
    scores, inputs = [], {}
    (ROOT / "scores").mkdir()
    try:
        for linked in result.linked_results:
            if linked.status != "linked_succeeded":
                continue
            cell = linked.cell
            signed = issue_linked_score_input(panel=result.compiled.panel, result=linked,
                task=result.compiled.tasks[cell.task_digest], scenario=result.compiled.scenarios[cell.key],
                package=result.compiled.packages[cell.runtime_arm.content_hash], authority=authority)
            inputs[cell.key] = signed
            score = client.submit(cell_key=cell.key, linked_input=signed)
            scores.append(score)
            name = FrozenRecord.from_dict(cell.data()).content_hash
            write(ROOT / "scores" / (name + ".json"), {"cell_key": list(cell.key), "linked_input": signed.data(), "score_receipt": score.receipt.data()})
            print(canonical({"stage": "adapted_cell_scored", "scored": len(scores), "expected": len(result.compiled.panel.cells)}), flush=True)
    finally:
        client.close()
    selected = measure_and_select_train(panel=result.compiled.panel,
        rule=FrozenTrainSelectionRule(FrozenRecord.from_dict(data["acceptance_criteria"]["train_adapted_selection"])),
        results=result.linked_results, tasks=result.compiled.tasks, scenarios=result.compiled.scenarios,
        packages={package.digest: package for package in result.compiled.packages.values()}, linked_inputs=inputs,
        scores=scores, config=ScorerConfig(FrozenRecord.from_dict(data["scorer"])),
        execution_authority_keys={EXECUTOR: execution_key}, scoring_authority_keys={SCORER: (PRIVATE / (SCORER + ".key")).read_bytes()})
    write(ROOT / "train-selection.json", selected.data())
    summary = {"execution_status": result.receipt.data()["execution_status"], "cells": len(result.compiled.panel.cells),
        "linked_statuses": result.receipt.data()["linked_statuses"], "scores": len(scores),
        "solver_calls": len(model.ledger["calls"]), "solver_tokens": model.ledger["tokens"], "usage_incomplete": model.ledger["usage_incomplete"],
        "selection_status": selected.data()["status"], "scientific_validity": "not_measured", "calibration": "not_measured",
        "mechanism_effect": "not_measured", "validation_items": 0, "source_commit": preflight["source_commit"]}
    write(ROOT / "metadata-summary.json", summary)
    print(canonical(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("action", choices=("prepare", "probe", "run"))
    args = parser.parse_args()
    if Path.cwd().resolve() != SOURCE.resolve():
        raise RuntimeError("Launch this script with the frozen integration checkout as cwd")
    try:
        {"prepare": prepare, "probe": probe, "run": run}[args.action]()
    except Exception as exc:
        if ROOT.exists():
            ledger_path = ROOT / "model/ledger.json"
            ledger = read(ledger_path) if ledger_path.is_file() else None
            failed = {"schema": "linked-train-attempt-failure-v1", "action": args.action,
                "error_type": type(exc).__name__, "expected_cells": 12,
                "solver_calls": len(ledger["calls"]) if ledger else 0,
                "solver_tokens": ledger["tokens"] if ledger else 0,
                "scored_cells": len(list((ROOT / "scores").glob("*.json"))),
                "unscored_cells_remain_in_denominator": True, "selection": "inconclusive",
                "scientific_validity": "not_measured", "validation_items": 0}
            failure_path = ROOT / (args.action + "-failure.json")
            if not failure_path.exists():
                write(failure_path, failed)
            print(canonical(failed), flush=True)
        raise SystemExit(1) from None
