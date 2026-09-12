"""Execute retained BLADE output once, without resuming or rescoring its pilot."""
import hashlib
import json
import shutil
from pathlib import Path
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionRequest
from research_loop.modular.contracts import DataIdentity
from research_loop.modular.model_port import inspect_terminal_call
from research_loop.ontology import canonical

original = Path(r"E:\_ryanDev\AI\research-loop-modular\integration\work\blade-reviewed-transport-20260912")
out = original.parent / "recovered-blade-diagnostic-20260912"
out.mkdir(exist_ok=False)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
before = {str(p.relative_to(original)): sha(p) for p in original.rglob("*") if p.is_file()}
contract = json.loads((original / "contract.json").read_text())
identity = DataIdentity.parse(contract["identity"])
identity.require_train()
packet_dir = Path(r"E:\_ryanDev\AI\research-loop-modular\benchmarks\work\train-packets-live-20260912-v3\blade\d90d6fb37453f6592fe9f0cb76384ac2778f60758d7b94a06728f725196ccad0")
assert sha(packet_dir / "data.csv") == contract["csv_sha256"]
inspection = inspect_terminal_call(original / "model", 1)
assert inspection.response is not None
assert inspection.receipt.data()["reconciled"] is False
(out / "inspection.json").write_text(inspection.receipt.encoded, encoding="utf-8")
program = out / "recovered-analysis.py"
program.write_text(inspection.response.data()["code"], encoding="utf-8")
shutil.copy2(packet_dir / "data.csv", out / "data.csv")
frozen = {"purpose": "recovered_BLADE_output_execution_diagnostic", "new_model_calls": 0,
    "max_executions": 1, "original_files": before, "original_contract_sha256": sha(original / "contract.json"),
    "identity": identity.data(), "program_sha256": sha(program), "csv_sha256": sha(out / "data.csv"),
    "image": contract["image"], "scientific_score": None, "original_pilot_status": "failed_unchanged"}
(out / "contract.json").write_text(canonical(frozen), encoding="utf-8")
execution = DockerExecutionBroker([out]).execute(ExecutionRequest(identity, contract["image"], program, {"data": out / "data.csv"}, 30))
assert before == {str(p.relative_to(original)): sha(p) for p in original.rglob("*") if p.is_file()}
report = {"execution_status": execution.status, "execution_digest": execution.content_hash,
    "execution": execution.data(), "new_model_calls": 0, "executions": 1, "original_unchanged": True,
    "scientific_score": None, "scientific_effect_measured": False,
    "limitation": "Read-only recovery of a failed transport pilot; no independent scientific audit or benchmark measurement"}
(out / "report.json").write_text(canonical(report), encoding="utf-8")
print(json.dumps({"execution_status": execution.status, "new_model_calls": 0, "stdout": execution.record.data().get("stdout", "")[:1600]}))
