"""A newly frozen BLADE transport diagnostic; never retries the old pilot."""
import hashlib
import json
import secrets
import subprocess
from pathlib import Path

from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.model_port import CodexModelPort, FrozenBaseContextPolicy
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import canonical, digest

root = Path(r"E:\_ryanDev\AI\research-loop-modular\integration\work\blade-reviewed-transport-20260912")
root.mkdir(exist_ok=False)
audit_root = Path(r"E:\_ryanDev\AI\research-loop-modular\work\context-policy-root-audit-20260912-v2")
policy = json.loads((audit_root / "UNQUALIFIED-POLICY.json").read_text())
assert policy["binding"]["context_digest"] == "90fefcde21ce37c3fb79474490bcafb647f8678e000e68783309c45506c07da2"
# Root reviewed the actual two visible messages and configuration inventory.
# This local transport review carries no scientific promotion authority.
policy.update(status="REVIEWED", review={
    "reviewer": "root controller / local transport context review",
    "reviewed_at": "2026-09-12 Asia/Shanghai",
    "rationale": "Exact visible context contains five bundled skill descriptions, general global instruction-entry references and the fixed empty public cwd. No benchmark labels, historical scores or private evaluation content are visible. All arms must reuse the same base binding. Debug does not establish remote model or full tool-schema identity.",
    "source_completeness": "Inspected default config key inventory: no external model/developer instruction-file fields and no profiles. Local configs/rules/skill sources and the explicit frozen model catalog are bound; tools, retrieval, plugins and MCP are disabled. Referenced global memory files are not loaded into this render. Filesystem/remote isolation is not claimed."})
policy_path = root / "REVIEWED-POLICY.json"
policy_path.write_text(canonical(policy), encoding="utf-8")
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
frozen = FrozenBaseContextPolicy(policy_path, sha(policy_path))
frozen.data()
packet_path = Path(r"E:\_ryanDev\AI\research-loop-modular\benchmarks\work\train-packets-live-20260912-v3\blade\d90d6fb37453f6592fe9f0cb76384ac2778f60758d7b94a06728f725196ccad0\public.json")
envelope = json.loads(packet_path.read_text())
identity = DataIdentity.parse(envelope["task"]["identity"])
identity.require_train()
task = PublicTask.create(identity, envelope["task"]["payload"])
csv = packet_path.parent / "data.csv"
assert task.content_hash == envelope["receipt"]["packet_hash"]
assert envelope["receipt"]["identity"] == identity.data()
assert sha(csv) == envelope["receipt"]["csv_sha256"]
assert identity.benchmark == "blade"
schema_analysis = {"type": "object", "properties": {"code": {"type": "string"}, "analysis": {"type": "string"}},
                   "required": ["code", "analysis"], "additionalProperties": False}
schema_final = {"type": "object", "properties": {"objective_digest": {"type": "string"},
    "outcome": {"type": "string", "enum": ["unknown"]}, "evidence_ids": {"type": "array", "items": {"type": "string"}},
    "conclusion": {"type": "string"}, "programme_complete": {"type": "boolean", "enum": [False]}},
    "required": ["objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"], "additionalProperties": False}
instruction = ("This is a bounded training transport diagnostic. Return a self-contained Python program that reads /input/data with pandas, "
    "inspects columns, missingness and outcome variability, and performs a suitable small analysis of the public question using available fields. "
    "Print compact numerical evidence and explicit limitations; skip any unidentified analysis. pandas, numpy and statsmodels are available. "
    "Do not claim scientific validity before execution or independent auditing. No network or additional files are available.")
final_instruction = ("Summarize the observed execution as a transport diagnostic only. Copy objective_digest from the supplied module context. "
    "No independent scientific audits or benchmark scores exist, so outcome must be unknown, evidence_ids must be empty, and programme_complete false. "
    "Mention failures or limits present in the execution output.")
image = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"
contract = {"purpose": "separate_BLADE_train_transport_diagnostic", "identity": identity.data(),
    "task_hash": task.content_hash, "packet_file_sha256": sha(packet_path), "csv_sha256": sha(csv),
    "reviewed_context_policy_sha256": frozen.sha256, "model": "gpt-5.6-luna", "effort": "low",
    "max_calls": 2, "max_executions": 1, "cumulative_token_ceiling": 25000, "image": image,
    "instructions": [instruction, final_instruction], "schemas": {"analysis": schema_analysis, "final": schema_final},
    "baseline_commit": "dfaebe554d8bae0191ece2251a812682054a2169",
    "implementation_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "scientific_effect_measured": False, "original_failed_Discovery_pilot": "retained_unchanged_no_retry",
    "execution_model_cwd": policy["binding"]["fixed_cwd"]}
(root / "contract.json").write_text(canonical(contract), encoding="utf-8")
port = CodexModelPort(policy["binding"]["cli_path"], root / "model", max_calls=2, max_tokens=25000,
    schema_by_slot=contract["schemas"], frozen_base_context=frozen)
keys = {"unused-audit-a": secrets.token_bytes(32), "unused-audit-b": secrets.token_bytes(32)}
session = RunSession(task, package_digest=digest(contract), arm=default_compatibility(contract["baseline_commit"]).arm([]),
    objective=FrozenRecord.from_dict({"question": task.payload.data()["research_question"], "purpose": contract["purpose"]}),
    slots=("analysis", "final"), execution_limit=1, sidecar=root / "runtime", verifier=AuditVerifier(keys), required_audit=("measurement",))
report = {"contract_digest": digest(contract), "scientific_score": None, "scientific_effect_measured": False}
try:
    print(canonical({"starting": identity.data(), "max_calls": 2}), flush=True)
    proposal = session.invoke("analysis", port, instruction=instruction)
    execution = session.execute(proposal.data()["code"], broker=DockerExecutionBroker([session.sidecar, csv.parent]),
        image=image, inputs={"data": csv}, timeout_seconds=30)
    report["execution"] = execution.record.data()
    print(canonical({"execution_status": execution.status, "starting_final_summary": True}), flush=True)
    response = session.invoke("final", port, instruction=final_instruction,
        module_context=FrozenRecord.from_dict({"objective_digest": session.objective.content_hash, "audits_available": False}))
    decision = session.finish(response)
    report.update({"status": "completed", "decision": decision.data(), "protocol": verify_protocol_trace(session.sidecar / "trace.jsonl").data(),
                   "model_tokens": port.ledger["tokens"], "model_calls": len(port.ledger["calls"])})
except Exception as exc:
    report.update({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc), "model_calls": len(port.ledger["calls"])})
    raise
finally:
    (root / "report.json").write_text(canonical(report), encoding="utf-8")
    print(canonical({"report": str(root / "report.json"), "status": report["status"], "model_calls": len(port.ledger["calls"])}), flush=True)
