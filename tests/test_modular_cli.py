import json
import subprocess
import sys

from research_loop.modular.contracts import FrozenRecord


def test_plan_cli_registers_complete_scope_without_claiming_results(tmp_path):
    path = tmp_path / "plan.json"
    args = [sys.executable, "-m", "research_loop.modular", "plan", "--baseline", "fixture-base", "--output", str(path)]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    plan = FrozenRecord(path.read_text(encoding="utf-8")).data()
    assert summary["scientific_status"] == "not_measured"
    assert len(plan["scenarios"]) == 48
    assert [len(plan[k]) for k in ["C1", "C2", "C3"]] == [9, 36, 5]
    assert plan["C5"]["target"] is None
    assert plan["meta_programme"]["separate_phase"] is True
    assert plan["validation_role"] == "acceptance_only"
    altered = args.copy()
    altered[altered.index("fixture-base")] = "different-base"
    assert subprocess.run(altered, capture_output=True).returncode != 0
