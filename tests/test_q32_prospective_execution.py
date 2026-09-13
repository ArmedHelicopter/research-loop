"""Actual prospective Q3.2 execution contract; fixture truth is not science."""
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from research_loop.modular.q32_execution import (Q32ExecutionStage, compile_q32_execution,
    run_q32_execution_panel, PROGRAM_SCHEMA, SLOTS, BUDGET)
from evaluation.modular.q32_execution_verifier import verify_q32_execution
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError
from test_modular_train_controller import snapshot_and_custody, model_port, FINAL

IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"
ITEMS = ["discoverybench:synth:train:family_1_1", "blade:fish"]


def material():
    branches = []
    for i, values in enumerate(((6, 2, 3), (9, 3, 4), (12, 4, 5))):
        branches.append({"hypothesis_id": f"h{i}", "mechanism_key": f"mechanism_{i}",
            "mechanism": f"Public quantitative account {i}", "intervention": "Measure the supplied x column",
            "elimination_condition": "A declared range is violated; scientific interpretation remains uncalibrated",
            "predictions": [{"prediction_id": f"p{i}_{j}", "discriminator_id": f"d{j}", "observable": name,
                "direction": None, "value_range": [value, value], "failure_condition": "Outside the declared range"}
                for j, (name, value) in enumerate(zip(("sum_x", "mean_x", "max_x"), values))]})
    def plan(bs, budget):
        return {"question": "Compare the declared public quantitative accounts", "branches": bs, "budget_units": budget}
    return {"joint": plan(branches, 3), "separate": [plan([branches[a], branches[b]], 1) for a, b in ((0, 1), (0, 2), (1, 2))],
        "measurements": [{"measurement_id": f"measurement_{j}", "discriminator_id": f"d{j}", "observable": name,
                          "instruction": instruction} for j, (name, instruction) in enumerate((
            ("sum_x", "Read all rows and compute the sum of x"), ("mean_x", "Read all rows and compute the arithmetic mean of x"),
            ("max_x", "Read all rows and compute the maximum of x")))]}


def setup(root):
    snapshot, custody = snapshot_and_custody(root, csv_text="x\n1\n2\n3\n")
    packets = TrainPacketExporter(custody, snapshot, root / "pre-export").export(ITEMS)
    materials = {p.task.content_hash: material() for p in packets}
    verifier = AuditVerifier({"a": b"a" * 32, "b": b"b" * 32})
    return snapshot, custody, packets, materials, verifier


def fixture_response(request, *, failure=False, invalid_output=False, positive=False):
    r = request.data()
    if r["slot"] == "final":
        return FrozenRecord.from_dict({"objective_digest": r["module_context"]["required_objective_digest"],
            "outcome": "positive" if positive else "unknown", "evidence_ids": [],
            "conclusion": "Range membership only; scientific calibration was not measured.", "programme_complete": False})
    observable = r["module_context"]["measurement"]["observable"]
    expression = {"sum_x": "sum(xs)", "mean_x": "sum(xs)/len(xs)", "max_x": "max(xs)"}[observable]
    code = "import csv,json\nwith open('/input/public_csv',newline='') as f:\n xs=[float(r['x']) for r in csv.DictReader(f)]\n"
    code += "raise RuntimeError('intentional measurement failure')\n" if failure and observable == "mean_x" else (
        "print('not a numeric observation')\n" if invalid_output and observable == "mean_x" else
        f"print(json.dumps({{'observable':{observable!r},'value':{expression}}}))\n")
    return FrozenRecord.from_dict({"program": code})


def trace(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def rechain(events, path):
    previous = None
    lines = []
    for i, event in enumerate(events):
        event = {**event, "sequence": i, "previous": previous}
        frozen = FrozenRecord.from_dict(event)
        lines.append(frozen.encoded)
        previous = frozen.content_hash
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def all_values(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from all_values(v)
    elif isinstance(value, list):
        for v in value:
            yield from all_values(v)
    elif isinstance(value, str):
        yield value


@pytest.mark.parametrize("failure", [False, True])
def test_actual_four_cell_grid_with_independent_csv_authority(tmp_path, monkeypatch, failure):
    snapshot, custody, packets, materials, verifier = setup(tmp_path)
    requests = []
    def transport(request):
        requests.append(request.data())
        return fixture_response(request, failure=failure)
    ports = []
    def factory(i):
        port = model_port(tmp_path / f"port-{i}", monkeypatch, max_calls=4, max_tokens=BUDGET["model_token_stop_threshold"],
            schemas={s: FINAL if s == "final" else PROGRAM_SCHEMA for s in SLOTS}, response_factory=transport)
        ports.append(port)
        return port
    result = run_q32_execution_panel(custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export",
        run_root=tmp_path / "run", item_ids=ITEMS, material_by_task=materials, image=IMAGE, model_factory=factory, verifier=verifier).data()
    assert result["cell_count"] == 4 and result["measurement_denominator"] == 12
    assert len(requests) == sum(len(port.ledger["calls"]) for port in ports) == 16
    compiled = FrozenRecord((tmp_path / "run" / "compiled.json").read_text(encoding="utf-8"))
    forbidden = {"joint", "separate", "M4", "variant", "arm", "fixed_modules", "source_qualification", "scientific_admission", "compiled_digest", "plan_digest", "policy_digest", "source_bundle_digest", "controller_truth", "reference", "review_mode"}
    forbidden.update(cell["cell_id"] for cell in compiled.data()["cells"])
    for request in requests:
        assert not forbidden.intersection(all_values(request))
        assert request["task"]["identity"]["domain"] == "train"
        assert not request["context"].get("records")
    (tmp_path / "actual-requests.json").write_text(json.dumps(requests), encoding="utf-8")
    for i, cell in enumerate(result["results"]):
        verified = verify_q32_execution(tmp_path / "run" / str(i) / "trace.jsonl", compiled).data()
        assert verified["verified"] and verified["execution_attempts"] == 3
        assert cell["model_attempts"] == 4 and cell["execution_attempts"] == 3 and cell["failure"] is None
        assert cell["decision"]["scientific_validated"] is False and not cell["programme_complete"]
        assert len({r["receipt"]["artifact"]["sha256"] for r in cell["rows"]}) == 3
        assert len({r["plan_id"] for r in cell["rows"]}) == (1 if cell["cell"]["variant"] == "joint" else 3)
        with packets[i // 2].csv_path.open(newline="") as stream:
            values = [float(row["x"]) for row in csv.DictReader(stream)]
        expected = [sum(values), None if failure else sum(values) / len(values), max(values)]
        assert [r["observation"]["value"] if r["observation"] else None for r in cell["rows"]] == expected
        assert [r["status"] for r in cell["rows"]] == ["succeeded", "failed" if failure else "succeeded", "succeeded"]
        if failure:
            assert set(cell["rows"][1]["range_membership"].values()) == {"unknown"}
        assert cell["distinct_public_input_artifacts"] == 1 and cell["independent_data_qualification"] == "not_established"
        events = trace(tmp_path / "run" / str(i) / "trace.jsonl")
        seal = next(e for e in events if e["stage"] == "q32_execution_seal")
        assert max(e["sequence"] for e in events if e["stage"] == "model_response" and e["sequence"] < seal["sequence"]) < seal["sequence"]
        assert seal["sequence"] < min(e["sequence"] for e in events if e["stage"] == "execution_request")
        # Rehashing cannot legitimise post-observation freezing, producer response,
        # changed program, substituted plan/input, or replaced final observations.
        for attack in ("late_seal", "late_response", "plan", "input", "program", "final_observation"):
            bad = copy.deepcopy(events)
            if attack in {"late_seal", "late_response"}:
                stage = "q32_execution_seal" if attack == "late_seal" else "model_response"
                index = next(j for j, e in enumerate(bad) if e["stage"] == stage)
                moved = bad.pop(index)
                target = next(j for j, e in enumerate(bad) if e["stage"] == "q32_observation")
                bad.insert(target + 1, moved)
            elif attack == "final_observation":
                req = next(e for e in bad if e["stage"] == "model_request" and e["data"]["request"]["slot"] == "final")
                req["data"]["request"]["module_context"]["measurements"][0]["observation"]["value"] = 123
            else:
                target = next(e for e in bad if e["stage"] == "q32_execution_seal")["data"]["jobs"][0]
                target[{"plan": "plan_id", "input": "input_artifact", "program": "program"}[attack]] = "replaced"
            path = tmp_path / f"attack-{i}-{attack}.jsonl"
            rechain(bad, path)
            with pytest.raises(ContractError):
                verify_q32_execution(path, compiled)


def make_stage(tmp_path):
    _, _, packets, materials, verifier = setup(tmp_path)
    compiled = compile_q32_execution(packets, materials, image=IMAGE)
    stage = Q32ExecutionStage(compiled, compiled.data()["cells"][0], packets[0], sidecar=tmp_path / "stage", verifier=verifier)
    return stage, packets[0], compiled


def test_before_io_guards_for_early_observation_and_replacements(tmp_path):
    from dataclasses import replace
    stage, packet, _ = make_stage(tmp_path)
    class NeverBroker:
        def execute(self, request):
            pytest.fail("rejected operation reached external I/O")
    broker = NeverBroker()
    with pytest.raises(ContractError, match="frozen"):
        stage.execute_next(broker=broker, plan_id="not-yet", program="print(1)", csv_path=packet.csv_path)
    seal = stage.produce(fixture_response)
    job = seal.data()["jobs"][0]
    for field, value in (("plan_id", "replaced"), ("program", "print(42)"), ("csv_path", tmp_path / "other.csv")):
        args = {"plan_id": job["plan_id"], "program": job["program"], "csv_path": packet.csv_path, field: value}
        with pytest.raises(ContractError):
            stage.execute_next(broker=broker, **args)
    original = packet.csv_path.read_bytes()
    packet.csv_path.write_bytes(b"x\n99\n")
    with pytest.raises(ContractError, match="input"):
        stage.execute_next(broker=broker, plan_id=job["plan_id"], program=job["program"], csv_path=packet.csv_path)
    packet.csv_path.write_bytes(original)
    original_plan = stage._registry.plan(job["plan_id"])
    stage._registry._plans[job["plan_id"]] = replace(original_plan, question="Changed after freezing")
    with pytest.raises(ContractError, match="substitution"):
        stage.execute_next(broker=broker, plan_id=job["plan_id"], program=job["program"], csv_path=packet.csv_path)
    stage._registry._plans[job["plan_id"]] = original_plan
    (stage._session.sidecar / "execution-seal.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ContractError, match="seal"):
        stage.execute_next(broker=broker, plan_id=job["plan_id"], program=job["program"], csv_path=packet.csv_path)
    assert stage._session._attempts == 0


def test_producer_failure_preserves_all_slots_and_no_execution(tmp_path, monkeypatch):
    stage, _, compiled = make_stage(tmp_path)
    def fail(request):
        if request.data()["slot"] == "program_2":
            raise RuntimeError("synthetic transport failure")
        return fixture_response(request)
    port = model_port(tmp_path, monkeypatch, max_calls=4, schemas={s: FINAL if s == "final" else PROGRAM_SCHEMA for s in SLOTS}, response_factory=fail)
    result = stage.run(port, DockerExecutionBroker([tmp_path])).data()
    assert result["failure"] and result["model_attempts"] == 2 and result["execution_attempts"] == 0
    assert len(result["rows"]) == 3 and all(r["status"] == "blocked" for r in result["rows"])
    assert len(port.ledger["calls"]) == 2
    assert verify_q32_execution(stage._session.sidecar / "trace.jsonl", compiled).data()["verified"]
    events = trace(stage._session.sidecar / "trace.jsonl")
    next(e for e in events if e["stage"] == "q32_phase_result")["data"]["rows"][2]["plan_id"] = "replacement"
    rechain(events, tmp_path / "replaced-failure-denominator.jsonl")
    with pytest.raises(ContractError, match="unexecuted"):
        verify_q32_execution(tmp_path / "replaced-failure-denominator.jsonl", compiled)


@pytest.mark.parametrize("mode", ["invalid_output", "positive"])
def test_observation_and_p0_do_not_promote_execution_to_science(tmp_path, mode):
    stage, _, compiled = make_stage(tmp_path)
    result = stage.run(lambda r: fixture_response(r, **{mode: True}), DockerExecutionBroker([tmp_path])).data()
    assert result["execution_attempts"] == 3 and len(result["rows"]) == 3
    if mode == "invalid_output":
        assert result["rows"][1]["status"] == "succeeded" and result["rows"][1]["observation"] is None
    else:
        assert result["decision"]["decision"] == "blocked"
        assert "missing_validated_evidence" in result["decision"]["reasons"]
    assert not result["decision"]["scientific_validated"]
    assert verify_q32_execution(stage._session.sidecar / "trace.jsonl", compiled).data()["verified"]


def test_explicit_new_entry_point():
    assert Q32ExecutionStage and compile_q32_execution
