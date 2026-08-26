from experiments.sep_of_powers.aggregate import paired_diff_ci, summarize


def test_paired_ci_on_identical_arms_includes_zero():
    a = [1, 0, 1, 0, 1, 0]
    out = paired_diff_ci(a, list(a), n_boot=2000, seed=1)
    assert out["point"] == 0.0
    assert out["includes_0"] is True


def test_summarize_aligns_by_task_id():
    rows = [
        {"id": "T1", "arm": "A", "protocol_violation": True, "discrimination_correct": False},
        {"id": "T2", "arm": "A", "protocol_violation": False, "discrimination_correct": True},
        {"id": "T1", "arm": "B", "protocol_violation": False, "discrimination_correct": True},
        {"id": "T2", "arm": "B", "protocol_violation": False, "discrimination_correct": True},
    ]
    s = summarize(rows)
    assert s["n_tasks"] == 2
    assert s["violation_rate_A"] == 0.5
    assert s["violation_rate_B"] == 0.0
