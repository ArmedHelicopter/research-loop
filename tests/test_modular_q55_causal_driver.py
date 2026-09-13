import hashlib
import hmac
import json
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter, DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.q55_causal_driver import Q55Driver, freeze_q55_causal_bundle, q55_injection
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError, canonical

IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"
VARIANTS = ("missing_data", "missing_method", "missing_budget", "missing_control")
AUTHORITY_KEYS = {"authority-a": b"a" * 32, "authority-b": b"b" * 32}


def task(name: str):
    identity = DataIdentity(name, "q55-" + name, name + ":public", "synthetic-v1", "f" * 64, "train")
    if name == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "synthetic-public",
            "research_question": "measure a public synthetic value", "data_schema": [{"name": "x", "dtype": "integer"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "measure a public synthetic value",
        "source_kind": "synthetic", "dataset": [{"name": "public", "columns": [{"name": "x"}]}]})


def source_rows():
    # Every arm retrieves this identical local, caller-owned pool. The two
    # selection IDs are controller-only; source IDs never reach the model.
    rows = []
    for number, (variant, lane) in enumerate((("data", "support"), ("method", "method"), ("budget", "counter"), ("control", "counter")), 1):
        rows.append({"source_id": "c%02d" % number, "root_source_id": "repair-root-%02d" % number,
                     "lane": lane, "text": "public closure material for " + variant})
    rows.extend([
        {"source_id": "o01", "root_source_id": "ordinary-root-01", "lane": "support", "text": "ordinary public support material"},
        {"source_id": "o02", "root_source_id": "ordinary-root-02", "lane": "method", "text": "ordinary public method material"},
        {"source_id": "o03", "root_source_id": "ordinary-root-03", "lane": "counter", "text": "ordinary public budget material"},
        {"source_id": "o04", "root_source_id": "ordinary-root-04", "lane": "counter", "text": "ordinary public control material"},
    ])
    return rows


def material(t, csv_path: Path, *, program=None):
    program = program or "from pathlib import Path\nprint(sum(int(x) for x in Path('/input/data_csv').read_text().split()[1:]))\n"
    csv = b"x\n1\n2\n"
    csv_path.write_bytes(csv)
    contract = {"contract_id": "q55-public-contract", "source_id": t.identity.group_id,
                "authorities": [{"authority_id": "authority-a", "source_group": "external-a"},
                                {"authority_id": "authority-b", "source_group": "external-b"}]}
    rows = {}
    for variant in VARIANTS:
        missing = variant.removeprefix("missing_")
        rows[variant] = {"availability": {name: name != missing for name in ("data", "method", "budget", "control")},
                         "program": program, "program_sha256": hashlib.sha256(program.encode()).hexdigest(), "image": IMAGE,
                         "inputs": {"data_csv": {"sha256": hashlib.sha256(csv).hexdigest(), "byte_count": len(csv)}},
                         "authority_contract": contract, "closure_source_id": {"data": "c01", "method": "c02", "budget": "c03", "control": "c04"}[missing],
                         "ordinary_source_id": {"data": "o01", "method": "o02", "budget": "o03", "control": "o04"}[missing]}
    return freeze_q55_causal_bundle(t, items=rows, sources=source_rows())


class PublicProvider:
    def __init__(self): self.calls = []
    def search(self, **kwargs):
        self.calls.append(kwargs)
        return tuple(document for document in kwargs["source_bundle"].documents if document.lane == kwargs["lane"])


class PublicAuthority:
    def __init__(self, *, status="passed", force_unresolved=False):
        self.calls = []; self.status = status; self.force_unresolved = force_unresolved
    def verify_closure(self, subject):
        self.calls.append(subject)
        data = subject.data(); contract = data["authority_contract"]
        # This fixture independently reads the literal input bytes and selected
        # caller record; it does not receive an arm or variant label.
        assert hashlib.sha256(bytes.fromhex(data["inputs"]["data_csv"]["bytes_hex"])).hexdigest() == data["inputs"]["data_csv"]["sha256"]
        assert hashlib.sha256(data["program"]["text"].encode()).hexdigest() == data["program"]["canonical_sha256"]
        selected = data["selected_source"]["text"]["text"]
        resolution = {name: (self.status == "passed" and not self.force_unresolved and selected == "public closure material for " + name)
                      for name in ("data", "method", "budget", "control")}
        observations = []
        for item in contract["authorities"]:
            observation = {"authority_id": item["authority_id"], "source_group": item["source_group"],
                           "contract_id": contract["contract_id"], "subject_digest": subject.content_hash,
                           "observation_digest": hashlib.sha256((item["authority_id"] + subject.content_hash).encode()).hexdigest(),
                           "status": self.status, "signature_verified": True, "resolution": resolution}
            observation["signature"] = hmac.new(AUTHORITY_KEYS[item["authority_id"]], canonical(observation).encode(), hashlib.sha256).hexdigest()
            observations.append(observation)
        return FrozenRecord.from_dict({"schema": "q55-causal-authority-receipt-v1", "subject_digest": subject.content_hash,
            "status": self.status, "observations": observations, "cost": {"unit": "verifier_units", "units": 2}, "resolution": resolution})


def scenario(t, bundle, variant, budget="a" * 64):
    body = {"experiment_id": "Q5.5", "variant": variant,
            "controller_input": q55_injection(task=FrozenRecord.from_dict(t.data()), evidence=bundle).data(),
            "base": {"task": t.content_hash, "evidence": bundle.content_hash, "budget": budget},
            "controls": {"same_task": True, "same_evidence": True, "same_budget": True}}
    return FrozenRecord.from_dict(body)


def candidate(t):
    return CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([t.identity]),
        changes={"prompt": {"instructions": "public synthetic diagnostic"}}, search_cost=0)


def model(request):
    data = request.data()
    return FrozenRecord.from_dict({"objective_digest": FrozenRecord.from_dict(data["objective"]).content_hash,
        "outcome": "unknown", "evidence_ids": [], "conclusion": "bounded public diagnostic", "programme_complete": False})


def cell_for(t, sc, package, variant, enabled):
    arm = default_compatibility("b" * 64).arm(enabled)
    return PanelCell("Q5.5", t.identity, "r0", variant, "arm", arm, t.content_hash, sc.content_hash, package.digest, "c" * 64)


def events(sidecar):
    return [FrozenRecord(line).data() for line in (sidecar / "trace.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("benchmark", ["blade", "discoverybench"])
@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("enabled", [(), ("M6",), ("M7",), ("M6", "M7")])
def test_q55_full_two_benchmark_factorial_uses_same_pool_and_real_docker(tmp_path, benchmark, variant, enabled):
    t = task(benchmark); csv_path = tmp_path / "public.csv"; bundle = material(t, csv_path); sc = scenario(t, bundle, variant)
    package = candidate(t); cell = cell_for(t, sc, package, variant, enabled); sidecar = tmp_path / "run"
    provider, authority = PublicProvider(), PublicAuthority()
    driver = Q55Driver(DockerExecutionBroker([tmp_path]), provider, authority, lambda _task, _bundle: {"data_csv": csv_path}, AUTHORITY_KEYS)
    session = RunSession(t, package_digest=package.digest, arm=cell.runtime_arm, objective=FrozenRecord.from_dict({"objective": "public synthetic"}),
        slots=("diagnostic", "final"), execution_limit=1, sidecar=sidecar, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    seen = []
    def recording_model(request):
        seen.append(request.data()); return model(request)
    _, final, _ = driver.run(ModularWorkflow(session), cell=cell, scenario=sc, model=recording_model, package=package)
    terminal = session.finish(final)
    trace = events(sidecar)
    assert terminal.data()["decision"] == "unknown"
    assert len(provider.calls) == 3 and len(authority.calls) == 1 and len(seen) == 2
    assert [call["lane"] for call in provider.calls] == ["support", "counter", "method"]
    # M6 changes actual selected public material; both arms incur the exact same provider budget.
    selected = authority.calls[0].data()["selected_source"]["source_id"]
    expected = {"data": ("c01", "o01"), "method": ("c02", "o02"), "budget": ("c03", "o03"), "control": ("c04", "o04")}[variant.removeprefix("missing_")]
    assert selected == (expected[0] if "M6" in enabled else expected[1])
    assert sum(event["stage"] == "execution_request" for event in trace) == (1 if "M6" in enabled else 0)
    assert any(event["stage"] == "q55_m7_permit" for event in trace) == ("M6" in enabled and "M7" in enabled)
    public_requests = json.dumps(seen)
    assert all(token not in public_requests for token in ("missing_data", "missing_method", "missing_budget", "missing_control", "M6", "M7", "restricted-public-retrieval"))
    assert all(set(request["module_context"].get("public_resource_material", [{}])[0]) <= {"lane", "text"} for request in seen if "public_resource_material" in request["module_context"])
    assert all("argv" not in json.dumps(request) and str(tmp_path) not in json.dumps(request) for request in seen)


def test_q55_failed_or_inconsistent_authority_never_resolves_or_executes(tmp_path):
    t = task("blade"); csv_path = tmp_path / "public.csv"; bundle = material(t, csv_path); sc = scenario(t, bundle, "missing_data")
    package = candidate(t); cell = cell_for(t, sc, package, "missing_data", ("M6", "M7")); sidecar = tmp_path / "run"
    class Inconsistent(PublicAuthority):
        def verify_closure(self, subject):
            receipt = super().verify_closure(subject).data(); receipt["status"] = "passed"; receipt["observations"][1]["status"] = "failed"; receipt["resolution"] = {name: True for name in ("data", "method", "budget", "control")}
            changed = receipt["observations"][1]
            signed = {key: changed[key] for key in ("authority_id", "source_group", "contract_id", "subject_digest", "observation_digest", "status", "signature_verified", "resolution")}
            changed["signature"] = hmac.new(AUTHORITY_KEYS[changed["authority_id"]], canonical(signed).encode(), hashlib.sha256).hexdigest()
            return FrozenRecord.from_dict(receipt)
    driver = Q55Driver(DockerExecutionBroker([tmp_path]), PublicProvider(), Inconsistent(), lambda _task, _bundle: {"data_csv": csv_path}, AUTHORITY_KEYS)
    session = RunSession(t, package_digest=package.digest, arm=cell.runtime_arm, objective=FrozenRecord.from_dict({"objective": "public synthetic"}), slots=("diagnostic", "final"), execution_limit=1, sidecar=sidecar, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    with pytest.raises(ContractError):
        driver.run(ModularWorkflow(session), cell=cell, scenario=sc, model=model, package=package)
    trace = events(sidecar)
    assert not any(event["stage"] == "execution_request" for event in trace)
    assert any(event["stage"] == "q55_authority_raw_response" for event in trace)
    assert any(event["stage"] == "q55_authority_failure" for event in trace)


def test_q55_rejects_bad_authority_signature_before_docker(tmp_path):
    t = task("blade"); csv_path = tmp_path / "public.csv"; bundle = material(t, csv_path); sc = scenario(t, bundle, "missing_data")
    package = candidate(t); cell = cell_for(t, sc, package, "missing_data", ("M6",)); sidecar = tmp_path / "run"
    class BadSignature(PublicAuthority):
        def verify_closure(self, subject):
            receipt = super().verify_closure(subject).data(); receipt["observations"][0]["signature"] = "0" * 64
            return FrozenRecord.from_dict(receipt)
    session = RunSession(t, package_digest=package.digest, arm=cell.runtime_arm, objective=FrozenRecord.from_dict({"objective": "public synthetic"}), slots=("diagnostic", "final"), execution_limit=1, sidecar=sidecar, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    with pytest.raises(ContractError):
        Q55Driver(DockerExecutionBroker([tmp_path]), PublicProvider(), BadSignature(), lambda _task, _bundle: {"data_csv": csv_path}, AUTHORITY_KEYS).run(ModularWorkflow(session), cell=cell, scenario=sc, model=model, package=package)
    assert not any(event["stage"] == "execution_request" for event in events(sidecar))


def test_q55_rejects_outer_resolution_tamper_without_new_signatures(tmp_path):
    t = task("blade"); csv_path = tmp_path / "public.csv"; bundle = material(t, csv_path); sc = scenario(t, bundle, "missing_data")
    package = candidate(t); cell = cell_for(t, sc, package, "missing_data", ("M6",)); sidecar = tmp_path / "run"
    class Tampered(PublicAuthority):
        def verify_closure(self, subject):
            receipt = super().verify_closure(subject).data(); receipt["resolution"] = {name: True for name in ("data", "method", "budget", "control")}
            return FrozenRecord.from_dict(receipt)
    session = RunSession(t, package_digest=package.digest, arm=cell.runtime_arm, objective=FrozenRecord.from_dict({"objective": "public synthetic"}), slots=("diagnostic", "final"), execution_limit=1, sidecar=sidecar, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    with pytest.raises(ContractError):
        Q55Driver(DockerExecutionBroker([tmp_path]), PublicProvider(), Tampered(), lambda _task, _bundle: {"data_csv": csv_path}, AUTHORITY_KEYS).run(ModularWorkflow(session), cell=cell, scenario=sc, model=model, package=package)
    assert not any(event["stage"] == "execution_request" for event in events(sidecar))


def test_q55_bounded_provider_stops_after_limit_and_journals_each_yield(tmp_path):
    t = task("blade"); csv_path = tmp_path / "public.csv"; bundle = material(t, csv_path); sc = scenario(t, bundle, "missing_data")
    package = candidate(t); cell = cell_for(t, sc, package, "missing_data", ("M6",)); sidecar = tmp_path / "run"
    class TooMany:
        def search(self, **kwargs):
            doc = next(document for document in kwargs["source_bundle"].documents if document.lane == kwargs["lane"])
            while True: yield doc
    session = RunSession(t, package_digest=package.digest, arm=cell.runtime_arm, objective=FrozenRecord.from_dict({"objective": "public synthetic"}), slots=("diagnostic", "final"), execution_limit=1, sidecar=sidecar, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    with pytest.raises(ContractError, match="exceeded"):
        Q55Driver(DockerExecutionBroker([tmp_path]), TooMany(), PublicAuthority(), lambda _task, _bundle: {"data_csv": csv_path}, AUTHORITY_KEYS).run(ModularWorkflow(session), cell=cell, scenario=sc, model=model, package=package)
    trace = events(sidecar)
    assert sum(event["stage"] == "q55_retrieval_item" for event in trace) == 8
    assert any(event["stage"] == "q55_retrieval_failure" for event in trace)


def test_q55_resolver_drift_rejects_before_provider_or_model(tmp_path):
    t = task("blade"); csv_path = tmp_path / "public.csv"; bundle = material(t, csv_path); csv_path.write_bytes(b"x\n99\n")
    sc = scenario(t, bundle, "missing_data"); package = candidate(t); cell = cell_for(t, sc, package, "missing_data", ("M6",))
    provider, authority = PublicProvider(), PublicAuthority()
    session = RunSession(t, package_digest=package.digest, arm=cell.runtime_arm, objective=FrozenRecord.from_dict({"objective": "public synthetic"}), slots=("diagnostic", "final"), execution_limit=1, sidecar=tmp_path / "run", verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    with pytest.raises(ContractError):
        Q55Driver(DockerExecutionBroker([tmp_path]), provider, authority, lambda _task, _bundle: {"data_csv": csv_path}, AUTHORITY_KEYS).run(ModularWorkflow(session), cell=cell, scenario=sc, model=model, package=package)
    assert provider.calls == [] and authority.calls == []
    assert [event["stage"] for event in events(tmp_path / "run")] == ["objective_lock"]


def test_q55_provider_partial_is_durable_before_failure(tmp_path):
    t = task("blade"); csv_path = tmp_path / "public.csv"; bundle = material(t, csv_path); sc = scenario(t, bundle, "missing_data")
    package = candidate(t); cell = cell_for(t, sc, package, "missing_data", ("M6",)); sidecar = tmp_path / "run"
    class Failure(Exception):
        partial_response = FrozenRecord.from_dict({"raw": "partial public retrieval"})
        cost = {"unit": "retrieval_calls", "units": 1}
    class Broken:
        def search(self, **_kwargs): raise Failure("provider stopped")
    session = RunSession(t, package_digest=package.digest, arm=cell.runtime_arm, objective=FrozenRecord.from_dict({"objective": "public synthetic"}), slots=("diagnostic", "final"), execution_limit=1, sidecar=sidecar, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    with pytest.raises(Failure):
        Q55Driver(DockerExecutionBroker([tmp_path]), Broken(), PublicAuthority(), lambda _task, _bundle: {"data_csv": csv_path}, AUTHORITY_KEYS).run(ModularWorkflow(session), cell=cell, scenario=sc, model=model, package=package)
    trace = events(sidecar); partial = next(index for index, event in enumerate(trace) if event["stage"] == "q55_retrieval_partial_response"); failure = next(index for index, event in enumerate(trace) if event["stage"] == "q55_retrieval_failure")
    assert partial < failure and trace[failure]["data"]["reported_cost"] == {"unit": "retrieval_calls", "units": 1}


def test_q55_freeze_rejects_boolean_availability_and_cross_lane_selection_before_calls(tmp_path):
    t = task("blade"); bundle = material(t, tmp_path / "public.csv"); raw = bundle.data()
    raw["items"]["missing_data"]["availability"]["data"] = 0
    with pytest.raises(ContractError):
        freeze_q55_causal_bundle(t, items=raw["items"], sources=raw["sources"])
    raw = bundle.data()
    raw["items"]["missing_data"]["ordinary_source_id"] = "o02"
    with pytest.raises(ContractError):
        freeze_q55_causal_bundle(t, items=raw["items"], sources=raw["sources"])


def test_q55_failed_docker_receipt_is_retained_without_promoting_closure(tmp_path):
    t = task("blade"); csv_path = tmp_path / "public.csv"
    bundle = material(t, csv_path, program="from pathlib import Path\nprint(Path('/input/data_csv').read_text())\nraise SystemExit(7)\n")
    sc = scenario(t, bundle, "missing_data"); package = candidate(t); cell = cell_for(t, sc, package, "missing_data", ("M6", "M7")); sidecar = tmp_path / "run"
    driver = Q55Driver(DockerExecutionBroker([tmp_path]), PublicProvider(), PublicAuthority(), lambda _task, _bundle: {"data_csv": csv_path}, AUTHORITY_KEYS)
    session = RunSession(t, package_digest=package.digest, arm=cell.runtime_arm, objective=FrozenRecord.from_dict({"objective": "public synthetic"}), slots=("diagnostic", "final"), execution_limit=1, sidecar=sidecar, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))
    _, final, _ = driver.run(ModularWorkflow(session), cell=cell, scenario=sc, model=model, package=package)
    terminal = session.finish(final)
    trace = events(sidecar)
    assert terminal.data()["decision"] == "unknown"
    assert any(event["stage"] == "execution_result" and event["data"]["status"] == "failed" for event in trace)
    final_request = next(event["data"]["request"] for event in trace if event["stage"] == "model_request" and event["data"]["request"]["slot"] == "final")
    assert final_request["module_context"]["resource_status"]["execution"] == "failed"
