"""Fresh no-paid solver/evaluator context render; no self-approval."""
import importlib.util
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_loop.modular.model_port import audit_base_context
from research_loop.ontology import canonical

isolation = Path(r"E:\_ryanDev\AI\research-loop-modular\work\q31-isolated-context")
spec = importlib.util.spec_from_file_location("fixed_child_environment", isolation / "context_environment_v2.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
previous = json.loads((isolation / "debug-root-20260913/REVIEWED-POLICY.json").read_text(encoding="utf-8"))
binding = previous["binding"]
output = Path(r"E:\_ryanDev\AI\research-loop-modular\work\linked-train-context-20260913-01")
candidate = audit_base_context(Path(binding["cli_path"]), Path(binding["fixed_cwd"]), output,
    source_specs=binding["source_specs"], config_overrides=tuple(binding["config_overrides"]),
    environment=module.child_environment())
current = json.loads(candidate.read_text(encoding="utf-8"))
summary = {"candidate": str(candidate), "paid_calls": 0, "context_digest": current["binding"]["context_digest"],
    "same_visible_context_as_previous": current["binding"]["context_digest"] == binding["context_digest"],
    "changed_binding_fields": [key for key in binding if binding[key] != current["binding"].get(key)], "review_status": "pending"}
(output / "audit-summary.json").write_text(canonical(summary), encoding="utf-8")
print(canonical(summary))
