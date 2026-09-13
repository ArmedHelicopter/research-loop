"""Direct linked scoring boundary regressions, including one real Docker cell."""
from dataclasses import replace
import hashlib

import pytest

from evaluation.modular.linked_scoring import (LinkedAdaptedScoringService, LinkedExecutionAuthority,
    issue_linked_score_input, verify_linked_score_input, verify_linked_adapted_receipt)
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint, FrozenRubricTransport
from research_loop.modular.benchmark_cell import run_benchmark_cell
from research_loop.modular.benchmarks import DockerExecutionBroker
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError
from test_modular_benchmark_cell import IMAGE, _audit, _model
from test_train_adapted_selection import material, EXEC, SCORER


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    return material(tmp_path_factory.mktemp("direct-linked-scoring"))[0]


def verify(args, *, score=None, source=None, cell=None, keys=None):
    chosen = args["panel"].cells[0] if cell is None else cell
    by_score = {item.cell_key: item for item in args["scores"]}
    return verify_linked_adapted_receipt(score or by_score[chosen.key], authority_keys=keys or {SCORER.authority_id: SCORER.key},
        config=args["config"], panel=args["panel"], cell=chosen,
        linked_input=source or args["linked_inputs"][chosen.key], execution_authority_keys={EXEC.authority_id: EXEC.key})


@pytest.mark.parametrize("field,value", [("metric_value", 1), ("dimension", True), ("rubric", "0" * 64),
    ("mode", "unfrozen"), ("evidence_schema", "wrong"), ("mechanism_trace_digest", "0" * 64),
    ("solver_trace_digest", "0" * 64), ("scientific_validity", "validated"), ("calibration", "passed")])
def test_authentic_but_inconsistent_issuer_receipts_are_rejected(chain, field, value):
    cell = chain["panel"].cells[0]
    original = next(row for row in chain["scores"] if row.cell_key == cell.key)
    body = original.receipt.data()["body"]
    if field == "metric_value": body["metric"]["value"] = value
    elif field == "dimension": body["metric"]["dimensions"][next(iter(body["metric"]["dimensions"]))] = value
    elif field == "rubric": body["evaluator_evidence"]["rubric_digest"] = value
    elif field == "mode": body["evaluator_evidence"]["mode"] = value
    elif field == "evidence_schema": body["evaluator_evidence"]["schema"] = value
    else: body[field] = value
    changed = replace(original, receipt=SCORER.issue(body))
    with pytest.raises(ContractError): verify(chain, score=changed)


def test_execution_and_scoring_authorities_cannot_be_the_same_even_at_verification(chain):
    cell = chain["panel"].cells[0]
    original = next(row for row in chain["scores"] if row.cell_key == cell.key)
    changed = replace(original, receipt=EXEC.issue(original.receipt.data()["body"]))
    with pytest.raises(ContractError, match="distinct"):
        verify(chain, score=changed, keys={EXEC.authority_id: EXEC.key})


def test_foreign_panel_member_and_tampered_program_are_rejected(chain):
    cell = chain["panel"].cells[0]
    foreign = replace(cell, scenario_digest="0" * 64)
    with pytest.raises(ContractError, match="exact frozen panel"):
        verify_linked_score_input(chain["linked_inputs"][cell.key], authority_keys={EXEC.authority_id: EXEC.key}, panel=chain["panel"], cell=foreign)
    source = chain["linked_inputs"][cell.key].data()
    source["body"]["candidate"]["program"] += "\nprint('not executed')"
    with pytest.raises(ContractError, match="signature"):
        verify(chain, source=FrozenRecord.from_dict(source))


def test_real_docker_program_and_answer_reach_anonymous_frozen_evaluator(chain, tmp_path):
    panel, config = chain["panel"], chain["config"]
    cell = next(cell for cell in panel.cells if cell.identity.benchmark == "blade")
    package = chain["packages"][cell.package_digest]
    data = tmp_path / "public.csv"; data.write_text("x\n1\n3\n", encoding="utf-8")
    result = run_benchmark_cell(cell=cell, task=chain["tasks"][cell.task_digest], scenario=chain["scenarios"][cell.key], package=package,
        objective=FrozenRecord.from_dict({"panel_digest": panel.digest}), mechanism_sidecar=tmp_path / "mechanism", solver_sidecar=tmp_path / "solver",
        public_inputs={"public_csv": data}, image=IMAGE, broker=DockerExecutionBroker([tmp_path]), model=_model([]), audit_verifier=_audit())
    source = issue_linked_score_input(panel=panel, result=result, task=chain["tasks"][cell.task_digest],
        scenario=chain["scenarios"][cell.key], package=package, authority=EXEC)
    candidate = source.data()["body"]["candidate"]
    assert candidate["program"] == result.solver.analysis.data()["program"]
    assert source.data()["body"]["executed_program_sha256"] == hashlib.sha256((tmp_path / "solver/analysis-1.py").read_bytes()).hexdigest()
    calls = []
    def resolver(handle, benchmark):
        return FrozenRecord.from_dict({"schema": "train-only-rubric-reference-v1", "split": "train", "benchmark": benchmark,
            "task_handle_digest": hashlib.sha256(handle.encode()).hexdigest(), "identity_digest": handle,
            "task_context": "synthetic", "references": [{"synthetic": True}]})
    def evaluator(request):
        calls.append(request.data())
        return FrozenRecord.from_dict({"cvars": 2, "transform": 2, "model": 2, "reason": "synthetic boundary only"})
    endpoint = FrozenBenchmarkRubricEndpoint(resolver=resolver, evaluator=evaluator, evaluator_id="synthetic-evaluator", evaluator_version="v1")
    identity = FrozenRecord.from_dict(cell.identity.data()).content_hash
    service = LinkedAdaptedScoringService(config=config, evaluator=FrozenRubricTransport(endpoint),
        execution_authority_keys={EXEC.authority_id: EXEC.key}, task_handles={identity: identity}, scorer_authority=SCORER)
    score = service.score_linked(panel=panel, cell=cell, linked_input=source)
    body = verify(chain, score=score, source=source, cell=cell).data()
    assert body["metric"]["value"] == 1 and body["scientific_validity"] == "not_measured"
    prompt = calls[0]["prompt"]
    assert "The synthetic mean is 2.0." in prompt and "2.0\\n" in prompt and "csv.DictReader" in prompt
    assert cell.package_digest not in prompt and str(tmp_path) not in prompt and "mechanism_provenance" not in prompt
