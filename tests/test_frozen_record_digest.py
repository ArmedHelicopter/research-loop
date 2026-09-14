"""Digest reuse preserves record semantics and never caches a validation decision."""
import json
from dataclasses import FrozenInstanceError, asdict

import pytest

from research_loop.modular.contracts import FrozenRecord, _large_record_digest
from research_loop.ontology import ContractError, canonical, digest


@pytest.mark.parametrize('size', [0, 4096, 524288])
def test_hash_matches_existing_json_contract_and_keeps_caller_copies_isolated(size):
    source = {'text': '\u4e2d\u6587\U0001f50e' * (size // 3), 'numbers': [0, -0.0, 1e-15, 10**40],
              'nested': {'null': None, 'bool': False, 'combining': 'e\u0301'}}
    record = FrozenRecord.from_dict(source)
    encoded = record.encoded
    expected = digest(json.loads(encoded))
    assert record.content_hash == record.content_hash == expected
    source['nested']['bool'] = True
    view = record.data(); view['nested']['bool'] = True
    assert record.data()['nested']['bool'] is False
    assert record.content_hash == expected and asdict(record) == {'encoded': encoded}
    with pytest.raises(FrozenInstanceError):
        record.encoded = canonical(source)


@pytest.mark.parametrize('replacement', [
    canonical({'text': 'b' * 5000}),
    json.dumps({'text': 'b' * 5000}),
    '{',
    '{"value":NaN}',
])
def test_hash_uses_current_content_even_after_bypassing_the_frozen_attribute_guard(replacement):
    record = FrozenRecord.from_dict({'text': 'a' * 5000})
    original = record.content_hash
    object.__setattr__(record, 'encoded', replacement)
    try:
        expected = digest(record.data())
    except (ValueError, TypeError) as error:
        with pytest.raises(type(error)):
            _ = record.content_hash
    else:
        assert record.content_hash == expected != original


def test_subclass_data_override_keeps_its_existing_hash_semantics():
    class AlternateView(FrozenRecord):
        def data(self):
            return {'alternate': True}
    record = AlternateView(canonical({'text': 'x' * 5000}))
    assert record.content_hash == digest({'alternate': True})


@pytest.mark.parametrize('encoded', ['{}\n', '{"a":1,"a":2}', '[]', '{"x":Infinity}'])
def test_reuse_does_not_bypass_constructor_canonical_object_validation(encoded):
    with pytest.raises(ContractError):
        FrozenRecord(encoded)


def test_large_record_reuse_has_a_bounded_retention_window():
    _large_record_digest.cache_clear()
    try:
        for n in range(20):
            record = FrozenRecord.from_dict({'text': 'x' * 5000, 'n': n})
            assert record.content_hash == digest(record.data())
        assert _large_record_digest.cache_info().currsize == 16
        before = _large_record_digest.cache_info()
        assert record.content_hash == digest(record.data())
        assert _large_record_digest.cache_info().hits == before.hits + 1
        oversized = FrozenRecord.from_dict({'text': 'x' * 524288})
        assert oversized.content_hash == digest(oversized.data())
        assert _large_record_digest.cache_info().currsize == 16
        assert _large_record_digest.cache_info().misses == before.misses
    finally:
        _large_record_digest.cache_clear()
