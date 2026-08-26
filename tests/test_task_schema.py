from pathlib import Path

from experiments.sep_of_powers.render_prompt import load_task
from experiments.sep_of_powers.score import load_label

ROOT = Path(__file__).resolve().parents[1]


def test_ids_match_and_rules_are_nonempty():
    for path in (ROOT / "data" / "tasks" / "pilot").glob("T*.json"):
        task = load_task(path)
        label = load_label(ROOT / "data" / "labels" / "pilot" / path.name)
        assert task["id"] == label["id"] == path.stem
        assert task["locked_rule"].strip()
        assert label["gold_status"].strip()
