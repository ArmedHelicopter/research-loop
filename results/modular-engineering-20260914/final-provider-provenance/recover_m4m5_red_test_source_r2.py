"""Restore the two unchanged context-line endings touched by the later patch."""
from pathlib import Path

prior = Path(__file__).with_name('recover_m4m5_red_test_source_r1.py')
source = prior.read_text(encoding='utf-8')
old = "assert sha(raw) == before['source_before'][name], 'no inferred source equality'"
repair = '''for context in (b"    assert result.receipt.data()['status']=='estimated'",
                b"    replay_grok_train_ledger(port)"):
    assert raw.count(context + b'\\n') == 1
    raw = raw.replace(context + b'\\n', context + b'\\r\\n', 1)
assert sha(raw) == before['source_before'][name], 'no inferred source equality'
'''
assert source.count(old) == 1
source = source.replace(old, repair).replace(
    'reverse only the three acde220 added assertions from captured exact green-r1 bytes',
    'reverse the three acde220 assertions and restore two touched context CRLFs; exact frozen SHA matches')
exec(compile(source, str(prior), 'exec'))
