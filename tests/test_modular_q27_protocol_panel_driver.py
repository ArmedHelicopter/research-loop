"""Public two-benchmark checks for the typed Q2.7 source/replay seam."""
from __future__ import annotations

import hashlib
import csv
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter, DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.admission import AuditItem, ScientificState
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.p0_panel import fixed_control_design
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.protocol_panel_driver import ProtocolReplayAuthority, Q27ProtocolDriver, freeze_protocol_bundle, protocol_panel_injection, verify_after_finish, verify_protocol_replay_receipt
from research_loop.modular.runtime import AuditAuthority, AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"
SPLIT = "7" * 64
AUDIT_KEYS = {"q27-a": b"a" * 32, "q27-b": b"b" * 32}


def _task(benchmark):
    identity = DataIdentity(benchmark, "q27-" + benchmark, benchmark + ":q27", "synthetic-v1", SPLIT, "train")
    if benchmark == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public",
            "research_question": "What public mean is observed?", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "What public mean is observed?",
        "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})


def _execution():
    csv = b"x\n1\n3\n"
    return {"program": "import csv, json\nwith open('/input/public_csv') as f: xs=[float(r['x']) for r in csv.DictReader(f)]\nprint(json.dumps({'mean':sum(xs)/len(xs)}))",
        "csv_bytes_hex": csv.hex(), "csv_sha256": hashlib.sha256(csv).hexdigest(),
        "image": IMAGE, "timeout_seconds": 20}


def _measurement(task):
    return {"source_id":task.identity.group_id,"contract_id":"synthetic-public-mean","method":"csv_mean","output_key":"mean"}


def _scenario(task, variant, control):
    grid = fixed_control_design("q" * 64, control.content_hash)
    bundle = freeze_protocol_bundle(task, execution=_execution(), p0_fixed_control=grid, measurement_contract=_measurement(task))
    injection = protocol_panel_injection(variant, task=FrozenRecord.from_dict(task.data()), evidence=bundle,
        p0_fixed_control=grid)
    budget = FrozenRecord.from_dict({"model_calls": 1, "docker_attempts": 1, "audit_receipts": 2})
    scenario = FrozenRecord.from_dict({"experiment_id": "Q2.7", "variant": variant,
        "controller_input": injection, "base": {"task": task.content_hash, "evidence": bundle.content_hash,
        "budget": budget.content_hash}, "controls": {"same_task": True, "same_evidence": True, "same_budget": True}})
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity]),
        changes={"prompt": {"instructions": "synthetic public train package"}}, search_cost=0)
    cell = PanelCell("Q2.7", task.identity, "r1", variant, "p0-fixed", FrozenRecord.from_dict(grid.data()["runtime_arm"]),
        task.content_hash, scenario.content_hash, package.digest, "a" * 64)
    return grid, scenario, package, cell


def _audit_port(calls, fault=None):
    def issue(subject):
        body=subject.data(); calls.append(body)
        if fault=='transport': raise OSError('synthetic audit transport failure')
        receipt=body['execution_receipt']; artifacts=body['public_artifacts']
        program=bytes.fromhex(artifacts['program_bytes_hex']); data=bytes.fromhex(artifacts['csv_bytes_hex'])
        assert hashlib.sha256(program).hexdigest()==receipt['artifact']['sha256']
        assert len(program)==receipt['artifact']['byte_count']
        assert hashlib.sha256(data).hexdigest()==receipt['record']['input_artifacts']['public_csv']['sha256']
        assert body['measurement_contract']['method']=='csv_mean'
        values=[float(r['x']) for r in csv.DictReader(io.StringIO(data.decode()))]
        observed=json.loads(receipt['record']['stdout'])
        passed=observed.get(body['measurement_contract']['output_key'])==sum(values)/len(values)
        state=ScientificState('valid','supported','unknown','explore')
        audit=[AuditItem('measurement',True,passed)]
        runtime=[]; material=[]
        for name,key in AUDIT_KEYS.items():
            authority=AuditAuthority(name,key)
            runtime.append(authority.issue(identity=DataIdentity.parse(body['identity']),objective_digest=body['objective_digest'],
                execution_digest=body['execution_digest'],state=state,outcome='positive',audit=audit).data())
            material.append(authority.issue_material(identity=DataIdentity.parse(body['identity']),subject_digest=subject.content_hash,
                execution_success=body['execution_status']=='succeeded',state=state,outcome='positive',audit=audit).data())
        result={'schema':'q27-audit-batch-v2','subject_digest':subject.content_hash,'material_receipts':material,
            'runtime_receipts':runtime,'cost':{'unit':'audit_units','units':2}}
        if fault=='partial': result['runtime_receipts']=runtime[:1]
        if fault=='subject': result['subject_digest']='0'*64
        if fault=='material_signature': result['material_receipts'][0]['mac']='0'*64
        if fault=='unknown_cost': result['cost']['units']=None
        if fault=='nonboolean':
            changed=result['material_receipts'][0]['body']; changed['execution_success']='true'
            # A typed boolean contract is checked even when this envelope is signed.
            import hmac
            from research_loop.ontology import canonical
            result['material_receipts'][0]['mac']=hmac.new(AUDIT_KEYS['q27-a'],canonical(changed).encode(),hashlib.sha256).hexdigest()
        return FrozenRecord.from_dict(result)
    return issue


def _model(seen, outcome="positive", blocked=False):
    def call(request):
        body = request.data(); seen.append(body)
        encoded = request.encoded
        for marker in ('"arm_id"', '"variant"', '"controller_input"', '"csv_bytes_hex"', '"p0_fixed_control"'):
            assert marker not in encoded
        public = body["module_context"]["public_execution"]
        assert set(public) == {"program_sha256", "csv_sha256", "image", "execution_digest", "execution_status"}
        assert json.loads(body["execution_feedback"][0]["stdout"]) == {"mean":2.0}
        return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"],
            "outcome": outcome, "evidence_ids": [] if blocked or outcome=="unknown" else [public["execution_digest"]],
            "conclusion": "The public execution returned the supplied rows.", "programme_complete": False})
    return call


def _run(root: Path, benchmark: str, variant: str, outcome="positive", blocked=False, audit_fault=None):
    task, control = _task(benchmark), FrozenRecord.from_dict({"p0": "trusted synthetic control"})
    grid, scenario, package, cell = _scenario(task, variant, control)
    sidecar = root / benchmark / variant; sidecar.mkdir(parents=True)
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm,
        objective=FrozenRecord.from_dict({"objective": "registered public execution endpoint"}), slots=("final",),
        execution_limit=1, sidecar=sidecar, verifier=AuditVerifier(AUDIT_KEYS), required_audit=("measurement",))
    calls, seen = [], []
    driver = Q27ProtocolDriver(broker=DockerExecutionBroker([sidecar]), audit_port=_audit_port(calls,audit_fault),
        expected_p0_control_digest=control.content_hash)
    stage, candidate, responses = driver.run(ModularWorkflow(session), cell=cell, scenario=scenario,
        model=_model(seen,outcome,blocked), package=package)
    terminal = session.finish(candidate)
    return task, grid, scenario, cell, session, stage, candidate, responses, terminal, calls, seen


@pytest.mark.parametrize("benchmark", ["blade", "discoverybench"])
@pytest.mark.parametrize("variant", ["missing_lock", "missing_execution", "missing_audit", "illegal_state"])
def test_complete_source_runs_have_identical_budget_and_a_refused_offline_fault_replay(tmp_path, benchmark, variant):
    _task_row, grid, scenario, cell, session, stage, candidate, responses, terminal, audits, seen = _run(tmp_path, benchmark, variant)
    source = session.sidecar / "trace.jsonl"; original = source.read_bytes()
    assert terminal.data()["decision"] == "proceed" and session._attempts == 1 and session._next_call == 1
    assert len(audits) == 1 and len(seen) == len(responses) == 1
    assert stage.detail.data()["budget"]["audit_calls"] == 1 and stage.detail.data()["budget"]["runtime_receipts"] == 2
    assert grid.data()["runtime_arm"] == cell.runtime_arm.data()
    authority = ProtocolReplayAuthority("replay", b"r" * 32)
    receipt = verify_after_finish(cell=cell, scenario=scenario, session=session, candidate=candidate, terminal=terminal,
        replay_authority=authority, expected_p0_control_digest=grid.data()["p0_control_digest"])
    finding = authority.verify(receipt).data()
    assert finding["fault"] == variant and finding["source_decision"] == "proceed"
    assert finding["replay_refusal"] and finding["status"] == "refused" and finding["actual"]["audit_calls"] == 1
    assert finding["actual"]["audit_cost"] == {"unit":"audit_units","units":2}
    assert verify_protocol_replay_receipt(receipt,cell=cell,scenario=scenario,source_trace_path=source,replay_authority=authority,expected_p0_control_digest=grid.data()["p0_control_digest"]).data()==finding
    assert source.read_bytes() == original
    replay = session.sidecar / finding["replay"]["path"]
    assert replay.exists() and replay.read_bytes() != original


def test_bundle_and_p0_mismatch_fail_before_docker_or_model(tmp_path):
    task, control = _task("blade"), FrozenRecord.from_dict({"p0": "trusted synthetic control"})
    grid = fixed_control_design("q" * 64, control.content_hash)
    bad = _execution(); bad["csv_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="CSV digest"):
        freeze_protocol_bundle(task, execution=bad, p0_fixed_control=grid, measurement_contract=_measurement(task))
    bundle = freeze_protocol_bundle(task, execution=_execution(), p0_fixed_control=grid, measurement_contract=_measurement(task))
    other = fixed_control_design("q" * 64, FrozenRecord.from_dict({"p0": "different"}).content_hash)
    with pytest.raises(ContractError, match="P0 control differs"):
        protocol_panel_injection("missing_lock", task=FrozenRecord.from_dict(task.data()), evidence=bundle,
            p0_fixed_control=other)
    assert not list(tmp_path.rglob("analysis-*.py"))


def test_replay_receipt_signature_and_source_candidate_binding_are_fail_closed(tmp_path):
    _task_row, grid, scenario, cell, session, _stage, candidate, _responses, terminal, _audits, _seen = _run(tmp_path, "blade", "missing_audit")
    authority = ProtocolReplayAuthority("replay", b"r" * 32)
    receipt = verify_after_finish(cell=cell, scenario=scenario, session=session, candidate=candidate, terminal=terminal,
        replay_authority=authority, expected_p0_control_digest=grid.data()["p0_control_digest"])
    forged = receipt.data(); forged["finding"]["fault"] = "missing_lock"
    with pytest.raises(ContractError, match="signature"):
        authority.verify(FrozenRecord.from_dict(forged))
    wrong = FrozenRecord.from_dict({**terminal.data(), "candidate_digest": "0" * 64})
    with pytest.raises(ContractError, match="candidate"):
        verify_after_finish(cell=cell, scenario=scenario, session=session, candidate=candidate, terminal=wrong,
            replay_authority=authority, expected_p0_control_digest=grid.data()["p0_control_digest"])


@pytest.mark.parametrize('outcome,blocked',[('unknown',False),('positive',True)])
def test_ineligible_source_retains_denominator_without_claiming_fault_detection(tmp_path,outcome,blocked):
    _,grid,scenario,cell,session,_,candidate,_,terminal,_,_=_run(tmp_path,'blade','missing_audit',outcome,blocked)
    authority=ProtocolReplayAuthority('replay',b'r'*32)
    receipt=verify_after_finish(cell=cell,scenario=scenario,session=session,candidate=candidate,terminal=terminal,replay_authority=authority,expected_p0_control_digest=grid.data()['p0_control_digest'])
    row=verify_protocol_replay_receipt(receipt,cell=cell,scenario=scenario,source_trace_path=session.sidecar/'trace.jsonl',replay_authority=authority,expected_p0_control_digest=grid.data()['p0_control_digest']).data()
    assert row['status']=='ineligible' and row['inconclusive'] and row['replay'] is None
    assert row['source_decision']==('blocked' if blocked else 'unknown')
    assert row['actual']['docker_attempts']==row['actual']['audit_calls']==row['actual']['model_calls']==1
    assert not (session.sidecar/'q27-replay'/'trace.jsonl').exists()


def test_repeat_hook_and_preexisting_replay_are_never_overwritten(tmp_path):
    _,grid,scenario,cell,session,_,candidate,_,terminal,_,_=_run(tmp_path,'blade','missing_lock')
    authority=ProtocolReplayAuthority('replay',b'r'*32)
    args=dict(cell=cell,scenario=scenario,session=session,candidate=candidate,terminal=terminal,replay_authority=authority,expected_p0_control_digest=grid.data()['p0_control_digest'])
    receipt=verify_after_finish(**args); path=session.sidecar/'q27-replay'/'trace.jsonl'; before=path.read_bytes()
    with pytest.raises(ContractError,match='already exists'): verify_after_finish(**args)
    assert path.read_bytes()==before
    assert FrozenRecord((path.parent/'receipt.json').read_text().strip())==receipt


@pytest.mark.parametrize('change',['decision','candidate','scenario','p0'])
def test_posthook_rejects_forged_terminal_and_foreign_bindings_before_writes(tmp_path,change):
    _,grid,scenario,cell,session,_,candidate,_,terminal,_,_=_run(tmp_path,'blade','missing_lock')
    authority=ProtocolReplayAuthority('replay',b'r'*32); expected=grid.data()['p0_control_digest']
    if change=='decision': terminal=FrozenRecord.from_dict({**terminal.data(),'decision':'unknown'})
    elif change=='candidate':
        candidate=FrozenRecord.from_dict({**candidate.data(),'conclusion':'forged'})
        terminal=FrozenRecord.from_dict({**terminal.data(),'candidate_digest':candidate.content_hash})
    elif change=='scenario': cell=replace(cell,scenario_digest='0'*64)
    elif change=='p0': expected='0'*64
    with pytest.raises(ContractError):
        verify_after_finish(cell=cell,scenario=scenario,session=session,candidate=candidate,terminal=terminal,replay_authority=authority,expected_p0_control_digest=expected)
    assert not (session.sidecar/'q27-replay').exists()


@pytest.mark.parametrize('fault',['transport','partial','subject','material_signature','nonboolean'])
def test_audit_failure_is_journaled_with_spent_attempt_and_unknown_cost(tmp_path,fault):
    with pytest.raises((ContractError,OSError)):
        _run(tmp_path,'blade','missing_audit',audit_fault=fault)
    events=[FrozenRecord(x).data() for x in (tmp_path/'blade'/'missing_audit'/'trace.jsonl').read_text().splitlines()]
    requests=[e for e in events if e['stage']=='q27_audit_request']; failures=[e for e in events if e['stage']=='q27_audit_failure']
    assert len(requests)==len(failures)==1 and requests[0]['data']['allocation']['audit_calls']==1
    assert requests[0]['data']['cost']['units'] is None and failures[0]['data']['cost']['units'] is None
    assert events.index(requests[0])<events.index(failures[0])
    assert not any(e['stage']=='model_request' for e in events)
    if fault!='transport':
        assert failures[0]['data']['reported_cost']['units']==2
        assert any(e['stage']=='q27_audit_response' for e in events)


@pytest.mark.parametrize('artifact',['program','csv'])
def test_actual_execution_byte_drift_stops_before_audit_and_model(tmp_path,monkeypatch,artifact):
    original=DockerExecutionBroker.execute
    def changed(self,request):
        path=request.program if artifact=='program' else request.inputs['public_csv']
        path.write_bytes(b"print('changed')\n" if artifact=='program' else b'x\n5\n7\n')
        return original(self,request)
    monkeypatch.setattr(DockerExecutionBroker,'execute',changed)
    with pytest.raises(ContractError,match='actual execution artifacts'):
        _run(tmp_path,'blade','missing_lock')
    events=[FrozenRecord(x).data() for x in (tmp_path/'blade'/'missing_lock'/'trace.jsonl').read_text().splitlines()]
    assert len([e for e in events if e['stage']=='execution_request'])==1
    assert not any(e['stage'] in ('q27_audit_request','model_request') for e in events)


@pytest.mark.parametrize('change',['replay_bytes','source_bytes','signed_scenario','replay_alias'])
def test_readonly_receipt_verifier_rejects_drift_and_aliases(tmp_path,change):
    _,grid,scenario,cell,session,_,candidate,_,terminal,_,_=_run(tmp_path,'blade','missing_lock')
    authority=ProtocolReplayAuthority('replay',b'r'*32); source=session.sidecar/'trace.jsonl'
    receipt=verify_after_finish(cell=cell,scenario=scenario,session=session,candidate=candidate,terminal=terminal,replay_authority=authority,expected_p0_control_digest=grid.data()['p0_control_digest'])
    replay=session.sidecar/'q27-replay'/'trace.jsonl'
    if change=='replay_bytes': replay.write_bytes(replay.read_bytes()+b'\n')
    elif change=='source_bytes': source.write_bytes(source.read_bytes()+b'\n')
    else:
        finding=authority.verify(receipt).data()
        if change=='signed_scenario': finding['scenario_digest']='0'*64
        else: finding['replay']['path']='trace.jsonl'
        receipt=authority.issue(FrozenRecord.from_dict(finding))
        (session.sidecar/'q27-replay'/'receipt.json').write_text(receipt.encoded)
    with pytest.raises((ContractError,ValueError)):
        verify_protocol_replay_receipt(receipt,cell=cell,scenario=scenario,source_trace_path=source,replay_authority=authority,expected_p0_control_digest=grid.data()['p0_control_digest'])
