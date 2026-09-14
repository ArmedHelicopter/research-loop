from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter, DockerExecutionBroker, ExecutionRequest
from research_loop.modular.benchmarks.scoring import blade_adapted_score, discovery_adapted_score
from research_loop.modular.contracts import DataIdentity
from research_loop.ontology import ContractError


def identity(benchmark: str, task_id: str = "task-1") -> DataIdentity:
    return DataIdentity(benchmark, task_id, "source-1", "v1", "train-1", "train")


def test_public_adapters_create_immutable_solver_envelopes() -> None:
    discovery = DiscoveryBenchAdapter().prepare(identity("discoverybench"), {
        "task_id": "task-1", "question": "What is associated with x?", "difficulty": "easy",
        "source_kind": "synthetic", "dataset": [{"name": "data.csv", "description": "public data", "columns": [{"name": "x", "description": "input"}]}],
    })
    blade = BladeAdapter().prepare(identity("blade"), {
        "task_id": "task-1", "dataset_id": "public-set", "research_question": "Estimate the association.",
        "data_schema": [{"name": "outcome", "description": "public", "dtype": "float"}], "task_instructions": "Use the supplied CSV.",
    })
    assert discovery.payload.data()["question"] == "What is associated with x?"
    assert blade.payload.data()["dataset_id"] == "public-set"
    assert discovery.payload.data()["source_kind"] == "synthetic"
    assert discovery.content_hash == DiscoveryBenchAdapter().prepare(identity("discoverybench"), discovery.payload.data()).content_hash


def test_adapters_reject_reference_or_gold_fields() -> None:
    with pytest.raises(ContractError):
        BladeAdapter().prepare(identity("blade"), {
            "task_id": "task-1", "dataset_id": "set", "research_question": "q", "data_schema": [],
            "task_instructions": "x", "reference": "hidden",
        })
    with pytest.raises(ContractError):
        DiscoveryBenchAdapter().prepare(identity("discoverybench"), {
            "task_id": "task-1", "question": "q", "source_kind": "synthetic", "dataset": [{"name": "x", "gold_hint": "no"}],
        })
    with pytest.raises(ContractError):
        DiscoveryBenchAdapter().prepare(identity("discoverybench"), {
            "task_id": "task-1", "question": "q", "dataset": [{"name": "x", "columns": []}],
        })


def test_adapter_to_broker_entrypoint_builds_restricted_docker_command(tmp_path: Path) -> None:
    public_root = tmp_path / "public"
    public_root.mkdir()
    program = public_root / "analysis.py"
    data = public_root / "data.csv"
    metadata = public_root / "metadata.json"
    program.write_text("print('ok')", encoding="utf-8")
    data.write_text("x\n1\n", encoding="utf-8")
    metadata.write_text("{}", encoding="utf-8")
    task = DiscoveryBenchAdapter().prepare(identity("discoverybench"), {
        "task_id": "task-1", "question": "q", "source_kind": "synthetic", "dataset": [{"name": "data.csv", "columns": []}],
    })
    seen: list[list[str]] = []
    def fake(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"ok\n", b"")
    receipt = DockerExecutionBroker([public_root], runner=fake).execute(
        ExecutionRequest(task.identity, "example/image@sha256:" + "a" * 64, program, {"data_csv": data, "metadata_json": metadata})
    )
    assert receipt.status == "succeeded"
    argv = seen[0]
    assert ["--pull", "never"] == argv[2:4]
    assert ["--network", "none"] == argv[argv.index("--network"):argv.index("--network") + 2]
    assert "--read-only" in argv and ["--user", "1000:1000"] == argv[argv.index("--user"):argv.index("--user") + 2]
    assert ":/input/data_csv:ro" in " ".join(argv)
    assert ":/task/analysis.py:ro" in " ".join(argv)
    assert task.payload.data()["dataset"][0]["name"] not in receipt.record.data()["argv"][-1]


def test_broker_rejects_outside_or_symlink_mount_without_running_docker(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    program = root / "analysis.py"
    program.write_text("print(1)", encoding="utf-8")
    outside = tmp_path / "outside.csv"
    outside.write_text("x", encoding="utf-8")
    receipt = DockerExecutionBroker([root], runner=lambda *_a, **_k: pytest.fail("runner must not run")).execute(
        ExecutionRequest(identity("blade"), "example/image@sha256:" + "a" * 64, program, {"data": outside})
    )
    assert receipt.status == "rejected"


def test_broker_rejects_parent_traversal_without_running_docker(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    program = root / "analysis.py"
    data = root / "data.csv"
    program.write_text("print(1)", encoding="utf-8")
    data.write_text("x", encoding="utf-8")
    traversing = root / "nested" / ".." / "data.csv"
    receipt = DockerExecutionBroker([root], runner=lambda *_a, **_k: pytest.fail("runner must not run")).execute(
        ExecutionRequest(identity("blade"), "example/image@sha256:" + "a" * 64, program, {"data": traversing})
    )
    assert receipt.status == "rejected"


def test_broker_rejects_mount_option_injection_without_running_docker(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    program = root / "analysis.py"
    injected = root / "data,ro.csv"
    program.write_text("print(1)", encoding="utf-8")
    injected.write_text("x", encoding="utf-8")
    receipt = DockerExecutionBroker([root], runner=lambda *_a, **_k: pytest.fail("runner must not run")).execute(
        ExecutionRequest(identity("blade"), "example/image@sha256:" + "a" * 64, program, {"data": injected})
    )
    assert receipt.status == "rejected"


def test_broker_returns_typed_unavailable_without_host_fallback(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    program = root / "analysis.py"
    data = root / "data.csv"
    program.write_text("print(1)", encoding="utf-8")
    data.write_text("x", encoding="utf-8")
    def no_docker(*_a: object, **_k: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("docker")
    receipt = DockerExecutionBroker([root], runner=no_docker).execute(
        ExecutionRequest(identity("blade"), "example/image@sha256:" + "b" * 64, program, {"data": data})
    )
    assert receipt.status == "unavailable"
    assert receipt.artifact is not None


def test_broker_classifies_daemon_connection_failure_as_infrastructure_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    program = root / "analysis.py"
    data = root / "data.csv"
    program.write_text("print(1)", encoding="utf-8")
    data.write_text("x", encoding="utf-8")
    def daemon_down(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 1, b"", b"Cannot connect to the Docker daemon")
    receipt = DockerExecutionBroker([root], runner=daemon_down).execute(
        ExecutionRequest(identity("blade"), "example/image@sha256:" + "b" * 64, program, {"data": data})
    )
    assert receipt.status == "unavailable"


def test_timeout_attempts_cleanup_of_only_its_owned_container(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    program = root / "analysis.py"
    data = root / "data.csv"
    program.write_text("print(1)", encoding="utf-8")
    data.write_text("x", encoding="utf-8")
    calls: list[list[str]] = []
    def timed_then_removed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        if argv[1:3] == ["run", "--pull"]:
            raise subprocess.TimeoutExpired(argv, 1)
        return subprocess.CompletedProcess(argv, 0, b"removed", b"")
    receipt = DockerExecutionBroker([root], runner=timed_then_removed).execute(
        ExecutionRequest(identity("blade"), "example/image@sha256:" + "c" * 64, program, {"data": data}, timeout_seconds=1)
    )
    assert receipt.status == "timed_out"
    assert calls[1][:3] == ["docker", "rm", "-f"]
    assert receipt.record.data()["cleanup"]["removed"] is True


def test_scoring_preserves_dimension_boundaries_and_empty_outputs() -> None:
    assert discovery_adapted_score("", {"context": 1, "variable_f1": 1, "relation": 1})["adapted_score"] == 0
    assert blade_adapted_score("answer", {"cvars": 1, "transform": 0.5, "model": 0})["adapted_score"] == 0.5
    with pytest.raises(ContractError):
        discovery_adapted_score("answer", {"context": float("nan"), "variable_f1": 1, "relation": 1})


def test_identical_concurrent_jobs_keep_distinct_names_and_timeout_cleanup(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import re
    import research_loop.modular.benchmarks.execution as execution
    monkeypatch.setattr(execution.time, 'time_ns', lambda: 123456789)
    program=tmp_path/'analysis.py';program.write_text('print(1)',encoding='utf-8')
    data=tmp_path/'data.csv';data.write_text('x\n1\n',encoding='utf-8')
    launched=[];removed=[];lock=threading.Lock()
    def runner(argv,**kwargs):
        with lock:
            if argv[1]=='run':
                launched.append(argv[argv.index('--name')+1])
                raise subprocess.TimeoutExpired(argv,1)
            assert argv[:3]==['docker','rm','-f']
            removed.append(argv[3])
        return subprocess.CompletedProcess(argv,0,b'removed',b'')
    request=ExecutionRequest(identity('blade'),'example/image@sha256:'+'c'*64,program,{'data':data},timeout_seconds=1)
    # Separate brokers model independent workers sharing the same Docker daemon.
    def run(_):return DockerExecutionBroker([tmp_path],runner=runner).execute(request)
    with ThreadPoolExecutor(max_workers=8) as pool:receipts=list(pool.map(run,range(32)))
    assert len(set(launched))==32 and set(launched)==set(removed) and len(removed)==32
    assert all(re.fullmatch('research-loop-[0-9a-f]{20}',name) for name in launched)
    assert all(r.status=='timed_out' and r.record.data()['cleanup']['removed'] for r in receipts)
