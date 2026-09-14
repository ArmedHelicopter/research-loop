"""Read-only independent probes for research-version artifacts at 2a8b360e."""
from __future__ import annotations
import json, shutil, sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(r"E:\_ryanDev\AI\research-loop-modular\research-version-artifacts")
OUT = Path(r"E:\_ryanDev\AI\research-loop-modular\work\research-version-independent-2a8b360e")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.research_versions import ResearchVersionBoundary
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError
from test_modular_retrieval_panel_drivers import _task


def session(path):
    task = _task("blade")
    return RunSession(task, package_digest="public", arm=default_compatibility("a" * 64).arm(("M1", "M6")),
        objective=FrozenRecord.from_dict({"question": "fixed"}), slots=("final",), execution_limit=0,
        sidecar=path, verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}), required_audit=("measurement",))

def freeze(subject):
    return FrozenRecord.from_dict({"schema":"independent-research-version-freeze-v1","subject_digest":subject.content_hash,
        "authorized":True,"scientific_verified":False})

def bad_authorization(s):
    # Deliberately unrelated receipt/subject/artifact reference; only type is checked.
    return FrozenRecord.from_dict({"schema":"anything-goes","receipt":{"forged":True},"subject":{"other":"binding"},"authority_artifact":s._event_artifacts[-1]})

def run():
    if OUT.exists():
        for p in OUT.iterdir():
            if p.name != Path(__file__).name:
                if p.is_dir(): shutil.rmtree(p)
                else: p.unlink()
    results = {"worker_head": __import__("subprocess").check_output(["git","-C",str(ROOT),"rev-parse","HEAD"], text=True).strip()}
    # Baseline frozen evidence is only read.
    closed = json.loads(Path(r"E:\_codex_tasks\research-version-artifacts\q86-frozen-r4-closed.json").read_text())
    results["frozen_r4"] = {k: closed[k] for k in ("commit","exit_code","source_unchanged","new_paid_calls","junit")}

    p = OUT / "invalid-authority"; p.mkdir()
    s = session(p); b = ResearchVersionBoundary(s)
    try:
        b.pause_and_freeze(FrozenRecord.from_dict({"question":"new"}), SimpleNamespace(freeze_version=freeze), bad_authorization(s))
        results["invalid_authorization"] = {"accepted": True, "child_persisted": b.child_path.exists(), "state": b.state,
            "child_authorization": b.child.data()["authorization"]}
    except Exception as exc:
        results["invalid_authorization"] = {"accepted": False, "error": type(exc).__name__, "detail": str(exc)}

    # Force the trace append path to fail after child disk publication.  This is
    # the meaningful mid-boundary failure point; retain all partial bytes.
    p = OUT / "trace-failure"; p.mkdir(); s = session(p); b = ResearchVersionBoundary(s)
    original = s._record
    def fail(stage, data):
        if stage == "research_version_child_persisted": raise OSError("injected trace append failure")
        return original(stage, data)
    s._record = fail
    try:
        b.pause_and_freeze(FrozenRecord.from_dict({"question":"new"}), SimpleNamespace(freeze_version=freeze), bad_authorization(s))
        results["trace_failure"] = {"raised": False}
    except Exception as exc:
        results["trace_failure"] = {"raised": True, "error": type(exc).__name__, "state": b.state,
            "child_memory": b.child is not None, "child_on_disk": b.child_path.exists(),
            "parent_on_disk": b.path.exists(), "terminal": s._terminal}
        try:
            b.assert_immutable(); results["trace_failure"]["still_usable"] = True
        except Exception as later:
            results["trace_failure"]["still_usable"] = False; results["trace_failure"]["later_error"] = type(later).__name__

    # Catalogue append fail after parent trace was written: constructor must not
    # return a usable boundary.
    p = OUT / "catalogue-failure"; p.mkdir(); s = session(p)
    old = s.record_artifact
    s.record_artifact = lambda **kw: (_ for _ in ()).throw(OSError("injected catalogue append failure"))
    try:
        ResearchVersionBoundary(s); results["catalogue_failure"] = {"raised": False}
    except Exception as exc:
        results["catalogue_failure"] = {"raised": True,"error":type(exc).__name__,"parent_on_disk":(p/"research-version-parent.json").exists(),"terminal":s._terminal}
    s.record_artifact = old

    # Static junction result: this Windows build exposes Path.is_junction, but
    # production _safe only probes attributes after stat (which follows target).
    results["junction_guard"] = {"path_is_junction_available": hasattr(Path("."), "is_junction"),
        "production_mentions_is_junction": "is_junction" in (ROOT/"research_loop/modular/research_versions.py").read_text()}
    (OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
if __name__ == "__main__": run()

