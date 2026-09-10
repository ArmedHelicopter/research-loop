from experiments.score_one_day import score


def assay():
    tasks, labels, rows, reviews = [], {}, [], {}
    for f in range(8):
        for i, expected in enumerate(("proceed", "closed_negative", "inconclusive", "withdrawn")):
            key = f"T{f}-{i}"
            tasks.append({"id": key, "family": f"F{f}", "evidence": [{"id": "protocol"}, {"id": "raw"}]})
            labels[key] = {"status": expected, "critical_evidence_ids": ["protocol", "raw"]}
            for arm in ("A", "B"):
                rows.append({"task_id": key, "arm": arm, "final": {"decision": {
                    "status": expected, "evidence_ids": ["protocol", "raw"]}}})
                reviews[key + ":" + arm] = {"reason_consistent": True}
    return tasks, labels, rows, reviews


def test_perfect_tie_is_not_incremental_evidence():
    result = score(*assay())
    assert result["metrics"]["B"]["correct_usable"] == 32
    assert result["conditional_sign_flip_p"] == 1
    assert result["quality_pass"] is False


def test_eight_family_improvements_reach_conditional_tail():
    tasks, labels, rows, reviews = assay()
    for row in rows:
        if row["arm"] == "A" and row["task_id"].endswith("-0"):
            row["final"]["decision"]["status"] = "invalid"
    result = score(tasks, labels, rows, reviews)
    assert result["conditional_sign_flip_p"] == 1 / 256
    assert result["quality_pass"] is True


def test_unreviewed_reasons_are_never_usable():
    tasks, labels, rows, _ = assay()
    result = score(tasks, labels, rows, {})
    assert result["metrics"]["B"]["exact_status"] == 32
    assert result["metrics"]["B"]["correct_usable"] == 0
    assert result["quality_pass"] is False
