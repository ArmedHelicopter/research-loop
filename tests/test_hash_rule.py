from experiments.sep_of_powers.score import hash_rule


def test_hash_rule_strips_and_is_stable():
    h = hash_rule("  abc  ")
    assert h == hash_rule("abc")
    assert len(h) == 64
    assert h != hash_rule("abd")
