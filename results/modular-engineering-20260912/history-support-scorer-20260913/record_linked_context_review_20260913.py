"""Record the completed bounded independent review; make no provider call."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_loop.modular.model_port import FrozenBaseContextPolicy, _reviewed_notice_messages
from research_loop.ontology import canonical

root = Path(r"E:\_ryanDev\AI\research-loop-modular\work\linked-train-context-20260913-01")
prior_path = Path(r"E:\_ryanDev\AI\research-loop-modular\work\q31-isolated-context\debug-root-20260913\REVIEWED-POLICY.json")
value = json.loads((root / "UNQUALIFIED-POLICY.json").read_text(encoding="utf-8"))
prior = json.loads(prior_path.read_text(encoding="utf-8"))
assert value["status"] == "UNQUALIFIED" and value["binding"] == prior["binding"]
entries = prior["allowed_startup_notices"]
assert len(entries) == 1 and entries[0]["kind"] == "disabled_code_mode_host"
_reviewed_notice_messages(value["binding"], entries)
value.update(status="REVIEWED", allowed_startup_notices=entries, review={
    "reviewer": "root controller with independent /root/review_panel_driver full-render review",
    "reviewed_at": datetime.now(timezone.utc).isoformat(),
    "rationale": "Independent reviewer inspected all five current audit files, including complete raw and visible messages. The raw role/content projection equals the two-message visible context: developer 2886 characters, user 547 characters. Only five isolated system skill descriptions, read-only settings, current environment and dedicated empty public cwd are visible. No global memory, benchmark task/answer, private reference, score, validation content or credential content is visible. Full context digest d81e41665461cda9c354e09c553772c6766299c603ddb6d11c9d3a440228b58c and all binding fields equal the previous reviewed render. No model call was made.",
    "source_completeness": "Current manifest contains 754 host .agents skill files, explicitly disabled and hash-bound to detect drift, plus isolated system skills, model catalogue, profile and ancestor configuration sources. Credential contents are excluded. Source inventory and full visible render were reviewed; this qualifies local context reproducibility and disabled tools only, not OS account isolation, remote model identity or scientific scoring calibration.",
    "startup_notice_rationale": "Exactly one policy-level disabled_code_mode_host notice is allowed. Root revalidated its exact message, frozen disabled flags and retained event-file hash using the production validator. Independent review confirmed the allowlist belongs at policy top level, not inside binding. No unstable-feature, skill-loading or other unknown context notice is allowed.",
})
target = root / "REVIEWED-POLICY.json"
with target.open("x", encoding="utf-8") as stream:
    stream.write(canonical(value))
sha = hashlib.sha256(target.read_bytes()).hexdigest()
FrozenBaseContextPolicy(target, sha).data()
receipt = {"schema": "linked-context-review-receipt-v1", "policy": str(target), "sha256": sha,
    "context_digest": value["binding"]["context_digest"], "paid_calls": 0,
    "visible_messages": 2, "visible_system_skills": 5, "host_skill_manifest_files": 754,
    "allowed_notice_kinds": [entry["kind"] for entry in entries], "status": "REVIEWED",
    "limits": ["not_OS_isolation", "not_remote_model_identity", "not_scorer_calibration"]}
(root / "review-receipt.json").write_text(canonical(receipt), encoding="utf-8")
print(canonical(receipt))
