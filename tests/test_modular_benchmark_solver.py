from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from research_loop.modular.benchmark_solver import run_benchmark_solve, verify_benchmark_solve_trace
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter, DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.runtime import AuditVerifier, verify_trace


IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"
KEYS = {"audit-a": b"a" * 32, "audit-b": b"b" * 32}


def task(benchmark: str = "discoverybench") -> PublicTask:
    identity = DataIdentity(benchmark, "synthetic-solver", "fixture-group", "v1", "fixture-split", "train")
    if benchmark == "blade":
        return BladeAdapter().prepare(identity, {"task_id": "synthetic-solver", "dataset_id": "synthetic-public-csv",
            "research_question": "What is the fixture mean?", "data_schema": [{"name": "x", "dtype": "number"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": "synthetic-solver", "question": "What is the fixture mean?",
        "source_kind": "synthetic", "dataset": [{"name": "public.csv", "description": "synthetic public CSV", "columns": [{"name": "x"}]}]})


def model(seen: list[dict[str, object]]):
    def callback(request: FrozenRecord) -> FrozenRecord:
        row = request.data(); seen.append(row)
        if row["slot"] == "analysis_program":
            return FrozenRecord.from_dict({"analysis": "Compute the mean of the public x column.",
                "program": "import csv\nwith open('/input/public_csv', newline='') as f:\n rows=list(csv.DictReader(f))\nprint(sum(float(r['x']) for r in rows)/len(rows))"})
        assert row["slot"] == "final_answer"
        assert row["execution_feedback"] and row["execution_feedback"][0]["stdout"].strip() == "2.0"
        return FrozenRecord.from_dict({"objective_digest": row["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [],
            "conclusion": "The fixture mean is 2.0.", "programme_complete": False})
    return callback


@pytest.mark.parametrize("benchmark", ["discoverybench", "blade"])
def test_public_task_model_program_docker_and_answer_are_trace_bound(tmp_path: Path, benchmark: str) -> None:
    public_root = tmp_path / "public"; public_root.mkdir()
    data = public_root / "public.csv"; data.write_text("x\n1\n3\n", encoding="utf-8")
    sidecar = tmp_path / "run"; sidecar.mkdir()
    seen: list[dict[str, object]] = []
    def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
        assert "--read-only" in argv and "--pull" in argv and argv[argv.index("--pull") + 1] == "never"
        return subprocess.CompletedProcess(argv, 0, b"2.0\n", b"")
    prepared = task(benchmark)
    result = run_benchmark_solve(task=prepared, public_inputs={"public_csv": data}, image=IMAGE,
        package_digest="fixture-package", arm=default_compatibility("fixture").arm(["M4", "M5"]),
        objective=FrozenRecord.from_dict({"question": "What is the fixture mean?"}), sidecar=sidecar,
        broker=DockerExecutionBroker([public_root, sidecar], runner=runner), model=model(seen),
        audit_verifier=AuditVerifier(KEYS), predecessor_context=FrozenRecord.from_dict({"q31_prediction": "mean is discriminating"}))
    assert result.execution is not None and result.execution.status == "succeeded"
    assert result.answer is not None and result.answer.data()["conclusion"] == "The fixture mean is 2.0."
    assert result.decision is not None and result.decision.data()["decision"] == "unknown"
    assert result.record.data()["scientific_effect"] == "not_measured"
    assert seen[0]["module_context"]["predecessor_context"]["q31_prediction"] == "mean is discriminating"
    assert seen[1]["module_context"]["analysis_digest"] == result.analysis.content_hash
    assert seen[1]["module_context"]["predecessor_context"]["q31_prediction"] == "mean is discriminating"
    assert verify_trace(tmp_path / "run" / "trace.jsonl").data()["terminal"] is True
    common = verify_protocol_trace(tmp_path / "run" / "trace.jsonl").data()
    assert common["structurally_verified"] is True
    protocol = verify_benchmark_solve_trace(tmp_path / "run" / "trace.jsonl", prepared).data()
    assert protocol["terminal"] == "final_decision" and protocol["identity"]["benchmark"] == benchmark


def test_execution_failure_still_reaches_answer_and_is_not_scientific_success(tmp_path: Path) -> None:
    public_root = tmp_path / "public"; public_root.mkdir()
    data = public_root / "public.csv"; data.write_text("x\n1\n3\n", encoding="utf-8")
    sidecar = tmp_path / "failed"; sidecar.mkdir()
    def failed_model(request: FrozenRecord) -> FrozenRecord:
        if request.data()["slot"] == "analysis_program":
            return FrozenRecord.from_dict({"analysis": "Attempt a public calculation.", "program": "raise SystemExit(7)"})
        return FrozenRecord.from_dict({"objective_digest": request.data()["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [],
            "conclusion": "The run failed, so the answer remains unresolved.", "programme_complete": False})
    result = run_benchmark_solve(task=task(), public_inputs={"public_csv": data}, image=IMAGE,
        package_digest="fixture-package", arm=default_compatibility("fixture").arm([]),
        objective=FrozenRecord.from_dict({"question": "What is the fixture mean?"}), sidecar=sidecar,
        broker=DockerExecutionBroker([public_root, sidecar], runner=lambda argv, **_: subprocess.CompletedProcess(argv, 7, b"", b"bad program")),
        model=failed_model, audit_verifier=AuditVerifier(KEYS))
    assert result.execution is not None and result.execution.status == "failed"
    assert result.answer is not None and result.decision is not None
    assert result.decision.data()["scientific_validated"] is False
    assert result.status == "execution_failed"


def test_outside_allowlist_is_a_terminal_denominator_before_any_model_call(tmp_path: Path) -> None:
    public_root = tmp_path / "public"; public_root.mkdir()
    outside = tmp_path / "outside.csv"; outside.write_text("x\n1\n", encoding="utf-8")
    sidecar = tmp_path / "run"; sidecar.mkdir()
    calls: list[FrozenRecord] = []
    result = run_benchmark_solve(task=task(), public_inputs={"public_csv": outside}, image=IMAGE,
        package_digest="fixture-package", arm=default_compatibility("fixture").arm([]),
        objective=FrozenRecord.from_dict({"question": "What is the fixture mean?"}), sidecar=sidecar,
        broker=DockerExecutionBroker([public_root, sidecar]), model=lambda request: calls.append(request) or FrozenRecord.from_dict({}),
        audit_verifier=AuditVerifier(KEYS))
    assert calls == []
    assert result.status == "input_preflight_failed"
    assert verify_trace(sidecar / "trace.jsonl").data()["terminal"] is True
    assert verify_protocol_trace(sidecar / "trace.jsonl").data()["structurally_verified"] is True


def test_model_exception_is_a_terminal_denominator(tmp_path: Path) -> None:
    public_root = tmp_path / "public"; public_root.mkdir()
    data = public_root / "public.csv"; data.write_text("x\n1\n", encoding="utf-8")
    sidecar = tmp_path / "run"; sidecar.mkdir()
    result = run_benchmark_solve(task=task(), public_inputs={"public_csv": data}, image=IMAGE,
        package_digest="fixture-package", arm=default_compatibility("fixture").arm([]),
        objective=FrozenRecord.from_dict({"question": "What is the fixture mean?"}), sidecar=sidecar,
        broker=DockerExecutionBroker([public_root, sidecar]), model=lambda _: (_ for _ in ()).throw(RuntimeError("fixture model failed")),
        audit_verifier=AuditVerifier(KEYS))
    assert result.status == "analysis_model_failed" and result.analysis is None
    assert verify_trace(sidecar / "trace.jsonl").data()["terminal"] is True
    assert verify_protocol_trace(sidecar / "trace.jsonl").data()["structurally_verified"] is True


def test_context_build_failure_is_a_terminal_denominator(tmp_path: Path, monkeypatch) -> None:
    public_root = tmp_path / "public"; public_root.mkdir()
    data = public_root / "public.csv"; data.write_text("x\n1\n", encoding="utf-8")
    sidecar = tmp_path / "run"; sidecar.mkdir()
    def fail_context(*_args, **_kwargs): raise RuntimeError("fixture context preflight failed")
    monkeypatch.setattr("research_loop.modular.runtime.ContextCache.get_or_build", fail_context)
    result = run_benchmark_solve(task=task(), public_inputs={"public_csv": data}, image=IMAGE,
        package_digest="fixture-package", arm=default_compatibility("fixture").arm([]),
        objective=FrozenRecord.from_dict({"question": "What is the fixture mean?"}), sidecar=sidecar,
        broker=DockerExecutionBroker([public_root, sidecar]), model=model([]), audit_verifier=AuditVerifier(KEYS))
    assert result.status == "analysis_model_failed"
    assert verify_protocol_trace(sidecar / "trace.jsonl").data()["structurally_verified"] is True


def test_docker_unavailable_is_a_terminal_denominator(tmp_path: Path) -> None:
    public_root = tmp_path / "public"; public_root.mkdir()
    data = public_root / "public.csv"; data.write_text("x\n1\n", encoding="utf-8")
    sidecar = tmp_path / "run"; sidecar.mkdir()
    result = run_benchmark_solve(task=task(), public_inputs={"public_csv": data}, image=IMAGE,
        package_digest="fixture-package", arm=default_compatibility("fixture").arm([]),
        objective=FrozenRecord.from_dict({"question": "What is the fixture mean?"}), sidecar=sidecar,
        broker=DockerExecutionBroker([public_root, sidecar], runner=lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("docker"))),
        model=model([]), audit_verifier=AuditVerifier(KEYS))
    assert result.status == "execution_unavailable" and result.answer is None
    assert verify_trace(sidecar / "trace.jsonl").data()["terminal"] is True
    assert verify_protocol_trace(sidecar / "trace.jsonl").data()["structurally_verified"] is True


def test_broker_exception_closes_pending_execution_for_common_protocol(tmp_path: Path) -> None:
    public_root = tmp_path / "public"; public_root.mkdir()
    data = public_root / "public.csv"; data.write_text("x\n1\n", encoding="utf-8")
    sidecar = tmp_path / "run"; sidecar.mkdir()
    class ExplodingBroker(DockerExecutionBroker):
        def execute(self, _request): raise RuntimeError("fixture broker failed")
    result = run_benchmark_solve(task=task(), public_inputs={"public_csv": data}, image=IMAGE,
        package_digest="fixture-package", arm=default_compatibility("fixture").arm([]),
        objective=FrozenRecord.from_dict({"question": "What is the fixture mean?"}), sidecar=sidecar,
        broker=ExplodingBroker([public_root, sidecar]), model=model([]), audit_verifier=AuditVerifier(KEYS))
    assert result.status == "execution_setup_failed"
    assert verify_protocol_trace(sidecar / "trace.jsonl").data()["structurally_verified"] is True


def test_live_docker_path_when_already_available(tmp_path: Path) -> None:
    inspect = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    if inspect.returncode:
        pytest.skip("local pinned Docker image is unavailable; test does not pull or start Docker")
    public_root = tmp_path / "public"; public_root.mkdir()
    data = public_root / "public.csv"; data.write_text("x\n1\n3\n", encoding="utf-8")
    sidecar = tmp_path / "live"; sidecar.mkdir()
    result = run_benchmark_solve(task=task(), public_inputs={"public_csv": data}, image=IMAGE,
        package_digest="fixture-package", arm=default_compatibility("fixture").arm([]),
        objective=FrozenRecord.from_dict({"question": "What is the fixture mean?"}), sidecar=sidecar,
        broker=DockerExecutionBroker([public_root, sidecar]), model=model([]), audit_verifier=AuditVerifier(KEYS))
    assert result.execution is not None and result.execution.status == "succeeded"
    assert result.decision is not None and result.decision.data()["scientific_validated"] is False
