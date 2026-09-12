"""Execute recovered output once as a diagnostic; never resume the old experiment."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionRequest
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.model_port import inspect_terminal_call

root = Path.cwd()
original = root / "results/modular-engineering-20260912/train-transport-20260912T193716"
packet_dir = Path("E:/_ryanDev/AI/research-loop-modular/benchmarks/work/train-packets-live-20260912-v3/discoverybench/1bb26390bcd74fc2a7397449164858ade3925a981f627d8c448cc9f601f68c65")
out = root / "work/recovered-train-diagnostic-20260912"
out.mkdir(exist_ok=False)
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
before = {str(p.relative_to(original)): sha(p) for p in original.rglob('*') if p.is_file()}
contract = json.loads((original / "contract.json").read_text())
packet = json.loads((packet_dir / "public.json").read_text())
identity = DataIdentity.parse(packet["task"]["identity"])
identity.require_train()
task = PublicTask.create(identity, packet["task"]["payload"])
assert task.content_hash == packet["receipt"]["packet_hash"] == contract["task_hashes"][0]
assert sha(packet_dir / "data.csv") == packet["receipt"]["csv_sha256"]
inspected = inspect_terminal_call(original / "model", 1)
assert inspected.response is not None and inspected.receipt.data()["reconciled"] is False
assert not inspected.receipt.data()["tool_events"]
(out / "inspection.json").write_text(inspected.receipt.encoded, encoding="utf-8")
program = out / "recovered-analysis.py"
program.write_text(inspected.response.data()["code"], encoding="utf-8")
shutil.copy2(packet_dir / "data.csv", out / "data.csv")
frozen = {"schema": "recovered-output-diagnostic-contract-v1", "purpose": "engineering_execution_only",
          "original_contract_sha256": sha(original / "contract.json"), "original_files": before,
          "inspection_digest": inspected.receipt.content_hash, "task": task.data(),
          "program_sha256": sha(program), "data_sha256": sha(out / "data.csv"), "image": contract["image"],
          "new_model_calls": 0, "max_executions": 1, "scientific_effect_measured": False,
          "original_experiment_status": "failed_unchanged", "context_faults_retained": True}
(out / "contract.json").write_text(FrozenRecord.from_dict(frozen).encoded, encoding="utf-8")
broker = DockerExecutionBroker([out])
execution = broker.execute(ExecutionRequest(identity, contract["image"], program, {"data": out / "data.csv"}, 30))
after = {str(p.relative_to(original)): sha(p) for p in original.rglob('*') if p.is_file()}
assert before == after
report = {"execution_status": execution.status, "execution_digest": execution.content_hash,
          "execution": execution.record.data(), "new_model_calls": 0, "executions": 1,
          "original_unchanged": True, "scientific_effect_measured": False,
          "limitation": "Recovered output from a context-contaminated pilot; no independent scientific audit or score"}
(out / "report.json").write_text(FrozenRecord.from_dict(report).encoded, encoding="utf-8")
print(json.dumps({"status": execution.status, "report": str(out / "report.json"), "new_model_calls": 0,
                  "stdout": execution.record.data().get("stdout", "")[:1200]}))
