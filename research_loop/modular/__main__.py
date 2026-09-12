"""Read-only experiment planning and controller evidence inspection commands."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import ContractError, FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.runtime import verify_trace


def programme_plan(baseline_digest: str) -> FrozenRecord:
    compatibility = default_compatibility(baseline_digest)
    triples = [("M2", "M3", "M5"), ("M4", "M5", "M6"), ("M1", "M4", "M7"),
               ("M3", "M6", "M9"), ("M7", "M8", "M9")]
    project_root = Path(__file__).resolve().parents[2]
    files = list((project_root / "research_loop/modular").rglob("*.py"))
    files += list((project_root / "evaluation/modular").rglob("*.py"))
    files += [project_root / "research_loop/ontology.py", project_root / "pyproject.toml"]
    sources = {file.relative_to(project_root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
               for file in sorted(files)}
    return FrozenRecord.from_dict({
        "schema": "modular-research-programme-v1", "baseline_digest": baseline_digest,
        "software_sources": sources, "compatibility": compatibility.manifest().data(),
        "scenarios": [spec.record.data() for spec in registry().values()],
        "C1": [compatibility.conditional_factorial([name]).data() for name in compatibility.names],
        "C2": [pair.data() for pair in compatibility.all_pairs()],
        "C3": [compatibility.conditional_factorial(triple).data() for triple in triples],
        "C4": {"full_and_ablation": compatibility.leave_one_out(compatibility.names).data(),
               "baseline": compatibility.arm(()).data(), "strong_control_status": "requires_frozen_compute_matched_package"},
        "C5": {"target": None, "status": "requires_train_selected_frozen_bundle"},
        "meta_programme": {"experiment_id": "Q6.3", "separate_phase": True},
        "required_benchmarks": ["discoverybench", "blade"], "optimization_domain": "train",
        "validation_role": "acceptance_only", "scientific_status": "not_measured",
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--baseline", required=True)
    plan.add_argument("--output", type=Path, required=True)
    trace = commands.add_parser("trace")
    trace.add_argument("path", type=Path)
    contrast = commands.add_parser("contrast")
    contrast.add_argument("spec", type=Path, help="controller score rows and predeclared contrast coefficients")
    args = parser.parse_args()
    if args.command == "plan":
        record = programme_plan(args.baseline)
        if args.output.exists() and args.output.read_text(encoding="utf-8") != record.encoded:
            raise ContractError("refusing to overwrite a different frozen programme plan")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(record.encoded, encoding="utf-8")
        print(json.dumps({"plan_digest": record.content_hash, "output": str(args.output.resolve()),
                          "scenarios": 48, "singleton_designs": 9, "pair_designs": 36, "triple_designs": 5,
                          "scientific_status": "not_measured"}))
    elif args.command == "trace":
        print(verify_trace(args.path).encoded)
    else:
        from evaluation.modular.statistics import estimate_contrast
        specification = json.loads(args.spec.read_text(encoding="utf-8"))
        print(estimate_contrast(**specification).encoded)


if __name__ == "__main__":
    main()
