"""Synthetic primary sources only; real adapter/custody/journal/signature seams."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.modular import primary_process_qualification as primary
from evaluation.modular.primary_validation_custody import (
    PrimaryValidationCustodian, PrimaryValidationResult, primary_validation_design_digest,
)
from evaluation.modular.train_io import prepare_primary_public_task
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.panel_receipts import (
    FrozenPanel, PanelCell, PanelReceiptVerifier, RuntimeReceipt, ScientificScorerReceipt,
    SignedAuthority, verify_signed,
)
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError, canonical, digest
from test_modular_custody_panel import DIGEST, PROTOCOL, calibration, obligations, acceptance
from test_primary_process_qualification import source_fixture, SECRET


def record(value):
    return FrozenRecord.from_dict(value)


def fixture(tmp_path):
    source_config = source_fixture(tmp_path / "synthetic", public_projection=True)
    audit, groups = primary.audit_primary_process(source_config)
    split = primary.partition_primary(audit, groups)
    reads = primary.PinnedReads(source_config["inputs"])
    state, items, _ = primary._inventory(source_config, reads)
    index, _ = primary._source_index(source_config, reads, state, items,
        reads.json("canonical_receipt"), reads.json("canonical_manifest"))
    held = {token for group in split["groups"] if group["split"] == "validation" for token in group["member_tokens"]}
    sources, buffers = [], {}
    for token in sorted(held):
        item = index[token]
        root = Path(source_config["snapshot_root"]) / ("discovery/upstream/discoverybench" if item.benchmark == "discoverybench"
                                                      else "scienceagent/work/BLADE/blade_bench/datasets") / item.relative_path
        metadata = (root / ("metadata_0.json" if item.benchmark == "discoverybench" else "info.json")).read_bytes()
        csv = (root / "data.csv").read_bytes()
        buffers[token] = metadata, csv
        sources.append({"token": token, "benchmark": item.benchmark, "official_split": item.official_split,
                        "metadata_sha256": hashlib.sha256(metadata).hexdigest(), "csv_sha256": hashlib.sha256(csv).hexdigest()})
    qualified = {"schema": "primary-validation-qualification-v1", "decision": "qualified_for_acceptance",
        "scope": "recorded_primary_split_provenance_exposure_v1", "split_digest": digest(split), "audit_digest": digest(audit),
        "input_bindings_digest": digest(audit["input_bindings"]), "source_evidence_digests": [digest("fixture source review")],
        "exposure_evidence_digests": [digest("fixture bounded exposure review")],
        "relationship_evidence_digests": [digest("fixture family review")], "sources": sources}
    design = default_compatibility(DIGEST).conditional_factorial(("M2",))
    criteria, candidate, config, rubric = (record({"fixture": name}) for name in ("criteria", "candidate", "config", "rubric"))
    design_digest = primary_validation_design_digest(SimpleNamespace(stage="V_final", scope_ids=("Q1.3",),
        legal_arm_grids={"Q1.3": design}, combinations=obligations(), required_benchmarks=primary.SOURCES))
    freeze = {"schema": "primary-validation-train-freeze-v1", "status": "frozen", "domain": "train",
              "candidate_digest": candidate.content_hash, "config_digest": config.content_hash, "rubric_digest": rubric.content_hash,
              "selection_rule_digest": digest("fixture train rule"), "training_receipts_digest": digest("fixture full train denominator"),
              "scorer_digest": DIGEST, "protocol_digest": PROTOCOL, "acceptance_criteria_digest": criteria.content_hash,
              "panel_design_digest": design_digest, "package_digests": [DIGEST]}
    args = dict(private_root=tmp_path / "private", sealed_split=record(split), sealed_audit=record(audit),
        qualification=SignedAuthority("qualified", b"q" * 32).issue(qualified), qualification_keys={"qualified": b"q" * 32},
        freeze=SignedAuthority("train", b"f" * 32).issue(freeze), freeze_keys={"train": b"f" * 32},
        candidate=candidate, config=config, rubric=rubric, custody_keys={"custody": b"s" * 32}, custody_authority="custody",
        calibration_keys={"calibration": b"k" * 32})
    custodian = PrimaryValidationCustodian(**args)
    cells, tasks = [], {}
    source_by_token = {row["token"]: row for row in sources}
    arms = {row["id"]: record(row["arm"]) for row in design.data()["cells"] if row["status"] == "executable"}
    for identity in custodian.identities():
        metadata, csv = buffers[identity.task_id]
        task = prepare_primary_public_task(identity, source_by_token[identity.task_id], json.loads(metadata), csv)
        tasks[task.content_hash] = task
        for variant in registry()["Q1.3"].variants:
            for arm_id, arm in arms.items():
                cells.append(PanelCell("Q1.3", identity, "fixture-r1", variant, arm_id, arm,
                                       task.content_hash, DIGEST, DIGEST, DIGEST))
    panel = FrozenPanel("V_final", "validation", custodian._allocation["digest"], candidate.content_hash,
        ("Q1.3",), {"Q1.3": design}, criteria, tuple(cells), obligations(), primary.SOURCES)
    return custodian, panel, args, buffers, qualified, freeze


def verifier():
    def score_verifier(score, cell, panel):
        body = verify_signed(score.receipt, {"scorer": b"j" * 32}, schema="independent-scored-cell-v1")
        assert body["cell_digest"] == record(cell.data()).content_hash
    return PanelReceiptVerifier(scorer_verifier=score_verifier, custody_keys={"custody": b"s" * 32},
        acceptance_keys={"accept": b"t" * 32}, calibration_keys={"calibration": b"k" * 32})


def evaluator(tmp_path, *, change=None):
    def evaluate(panel, materials, lease):
        assert {m.task.identity.benchmark for m in materials} == set(primary.SOURCES)
        assert all(SECRET not in canonical(m.task.data()) for m in materials)
        tasks = {material.task.content_hash: material.task for material in materials}
        rows, scores = [], []
        for i, cell in enumerate(panel.cells):
            task = tasks[cell.task_digest]
            run = RunSession(task, package_digest=cell.package_digest, arm=cell.runtime_arm,
                objective=record({"question": "synthetic fixed held-out evaluation"}), slots=("only",), execution_limit=0,
                sidecar=tmp_path / str(i), verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("audit",))
            candidate = record({"objective_digest": run.objective.content_hash, "outcome": "unknown", "evidence_ids": [],
                                "conclusion": "synthetic fixture", "programme_complete": False})
            context = record({"panel_cell": {"experiment_id": cell.coverage_id, "variant": cell.variant, "replicate": cell.replicate,
                                            "arm_id": cell.arm_id, "scenario_digest": cell.scenario_digest}})
            response = run.invoke("only", lambda _: candidate, instruction="fixed fixture", module_context=context)
            terminal = run.finish(response)
            row = RuntimeReceipt(cell.key, "succeeded", run.sidecar / "trace.jsonl", run._events[-1].content_hash,
                                 record({"responses": [response.data()], "terminal": terminal.data()}).content_hash)
            rows.append(row)
            scores.append(ScientificScorerReceipt(cell.key, SignedAuthority("scorer", b"j" * 32).issue({
                "schema": "independent-scored-cell-v1", "cell_digest": record(cell.data()).content_hash,
                "runtime_trace_digest": row.trace_digest, "scorer_digest": cell.scorer_digest})))
        signed = acceptance(panel, tuple(rows), tuple(scores), lease)
        if change == "missing_score":
            scores.pop()
        return PrimaryValidationResult(tuple(rows), tuple(scores), signed)
    return evaluate


def execute(custodian, panel, buffers, tmp_path, *, change=None):
    calibrated = calibration(panel.digest, primary.SOURCES)
    lease_id = custodian.lease(panel, calibrated)
    calls = []
    def provider(token):
        assert custodian.store.state["leases"][lease_id]["status"] == "consumed"
        calls.append(token)
        return buffers[token]
    aggregate = custodian.run(panel=panel, lease_id=lease_id, calibration=calibrated, source_provider=provider,
                              evaluate=evaluator(tmp_path / "runtime", change=change), verifier=verifier())
    return lease_id, aggregate, calls


def test_real_primary_projection_consumed_lease_signed_acceptance_and_replay(tmp_path):
    custodian, panel, args, buffers, _, _ = fixture(tmp_path)
    original = custodian.split.encoded
    lease_id, aggregate, calls = execute(custodian, panel, buffers, tmp_path)
    assert len(calls) == 2 and set(calls) == set(buffers)
    assert aggregate.data()["decision"] == "inconclusive"
    assert aggregate.data()["observed_cells"] == len(panel.cells)
    assert aggregate.data()["optimization_feedback_permitted"] is False
    assert all(token not in aggregate.encoded for token in buffers)
    assert SECRET not in aggregate.encoded and "trace_path" not in aggregate.encoded
    assert custodian.split.encoded == original and custodian.split.data()["independence_proven"] is False
    reopened = PrimaryValidationCustodian(**args)
    assert reopened.replay(panel=panel, lease_id=lease_id, verifier=verifier()) == aggregate
    with pytest.raises(ContractError, match="one-use|allocated or consumed"):
        reopened.lease(panel, calibration(panel.digest, primary.SOURCES))
    with pytest.raises(ContractError, match="consumed"):
        reopened.run(panel=panel, lease_id=lease_id, calibration=calibration(panel.digest, primary.SOURCES),
                     source_provider=lambda _: pytest.fail("reused lease read a source"),
                     evaluate=lambda *_: pytest.fail("reused lease evaluated"), verifier=verifier())


@pytest.mark.parametrize("fault", ["prefreeze", "candidate", "config", "rubric", "unqualified", "qualification_signature"])
def test_frozen_and_qualified_evidence_required_before_state_or_exposure(tmp_path, fault):
    _, _, args, _, qualified, freeze = fixture(tmp_path)
    args["private_root"] = tmp_path / "refused"
    if fault == "prefreeze":
        freeze["status"] = "proposed"
        args["freeze"] = SignedAuthority("train", b"f" * 32).issue(freeze)
    elif fault in {"candidate", "config", "rubric"}:
        args[fault] = record({"changed": fault})
    elif fault == "unqualified":
        qualified["decision"] = "unproven"
        args["qualification"] = SignedAuthority("qualified", b"q" * 32).issue(qualified)
    else:
        args["qualification"] = SignedAuthority("qualified", b"x" * 32).issue(qualified)
    with pytest.raises(ContractError):
        PrimaryValidationCustodian(**args)
    assert not args["private_root"].exists()


def test_train_identity_or_changed_design_cannot_be_leased(tmp_path):
    custodian, panel, *_ = fixture(tmp_path)
    train = next(row for row in custodian._rows if row["domain"] == "train")
    identities = {cell.identity: replace(cell.identity, task_id=train["token"], group_id=train["group"])
                  for cell in panel.cells if cell.identity.benchmark == train["source"]}
    mixed = replace(panel, cells=tuple(replace(cell, identity=identities.get(cell.identity, cell.identity)) for cell in panel.cells))
    with pytest.raises(ContractError, match="custody"):
        custodian.lease(mixed, calibration(mixed.digest, primary.SOURCES))
    with pytest.raises(ContractError):
        custodian.lease(replace(panel, stage="changed"), calibration(panel.digest, primary.SOURCES))
    assert not custodian.store.state["leases"]


@pytest.mark.parametrize("fault", ["source", "trace", "score", "subject", "aggregate", "candidate_after"])
def test_private_retained_evidence_tampering_is_rejected(tmp_path, fault):
    custodian, panel, _, buffers, *_ = fixture(tmp_path)
    lease_id, _, _ = execute(custodian, panel, buffers, tmp_path)
    root = custodian.root / "runs" / lease_id
    path = root / "evidence.json"
    evidence = json.loads(path.read_bytes())
    if fault == "source":
        (root / "sources" / next(iter(buffers)) / "data.csv").write_bytes(b"tampered")
    elif fault == "trace":
        Path(evidence["runtime"][0]["trace_path"]).write_bytes(b"tampered")
    elif fault == "score":
        evidence["scores"][0]["receipt"]["body"]["runtime_trace_digest"] = DIGEST
        path.write_text(canonical(evidence))
    elif fault == "subject":
        evidence["panel_digest"] = DIGEST
        path.write_text(canonical(evidence))
    elif fault == "aggregate":
        (root / "aggregate.json").write_bytes(b"{}")
    else:
        custodian.candidate = record({"post_validation_optimization": True})
    with pytest.raises(ContractError):
        custodian.replay(panel=panel, lease_id=lease_id, verifier=verifier())


def test_missing_score_keeps_consumed_opportunity_and_private_failure(tmp_path):
    custodian, panel, _, buffers, *_ = fixture(tmp_path)
    with pytest.raises(ContractError, match="successful cell"):
        execute(custodian, panel, buffers, tmp_path, change="missing_score")
    lease_id = next(iter(custodian.store.state["leases"]))
    root = custodian.root / "runs" / lease_id
    assert custodian.store.state["leases"][lease_id]["status"] == "consumed"
    assert json.loads((root / "failure.json").read_bytes())["retry_permitted"] is False
    assert json.loads((root / "failure.json").read_bytes())["expected_cells"] == len(panel.cells)
    assert (root / "evidence.json").is_file() and not (root / "aggregate.json").exists()
    with pytest.raises(ContractError, match="failed attempt"):
        custodian.replay(panel=panel, lease_id=lease_id, verifier=verifier())


def test_verifier_time_mutation_rejected_at_final_readback(tmp_path):
    custodian, panel, _, buffers, *_ = fixture(tmp_path)
    lease_id, _, _ = execute(custodian, panel, buffers, tmp_path)
    trusted = verifier()
    original_verify = trusted.verify
    def mutating_verify(*args, **kwargs):
        result = original_verify(*args, **kwargs)
        source = custodian.root / "runs" / lease_id / "sources" / next(iter(buffers)) / "data.csv"
        source.write_bytes(b"mutation after validation")
        return result
    trusted.verify = mutating_verify
    with pytest.raises(ContractError, match="changed during verification"):
        custodian.replay(panel=panel, lease_id=lease_id, verifier=trusted)
