"""Actual joint consumer and common reader must preserve journal bytes and mtime."""
from pathlib import Path
import os

import pytest

from research_loop.modular.m4_m5_artifacts import read_m4_m5_journals
from research_loop.modular.combination_benchmark_driver import verify_m4_m5_combination_benchmark_cell
from research_loop.modular.benchmarks import DockerExecutionBroker
from research_loop.ontology import ContractError
from test_modular_combination_benchmark_driver import _catalogue, _run, _model
from test_modular_prediction_scenarios import public_task


@pytest.mark.parametrize('arm', ['00', '01', '10', '11'])
def test_actual_combination_consumer_does_not_touch_any_file(tmp_path, monkeypatch, arm):
    catalogue = _catalogue()
    panel = catalogue.panels['pair:M4+M5']
    cell = next(c for c in panel.cells if c.arm_id == arm)
    seen = []
    call = _model(seen)
    def model(request):
        result = call(request)
        if request.data()['slot'] == 'm5_measurement':
            (tmp_path / 'public/public.csv').unlink()
        return result
    def no_execution(*args, **kwargs):
        pytest.fail('input preflight must prevent Docker execution')
    monkeypatch.setattr(DockerExecutionBroker, 'execute', no_execution)
    result = _run(panel, cell, catalogue, tmp_path, model)
    assert len(seen) == 3 and result.solver.status == 'input_preflight_failed'
    root = result.runtime.trace_path.parent
    # A fixed old timestamp makes even same-clock-tick touch() observable.
    for path in root.iterdir():
        if path.is_file():
            os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    def snapshot():
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir() if p.is_file()}
    before = snapshot()
    def no_touch(*args, **kwargs):
        pytest.fail('reader called Path.touch')
    monkeypatch.setattr(Path, 'touch', no_touch)
    assert verify_m4_m5_combination_benchmark_cell(result, panel=panel,
        task=catalogue.tasks[cell.task_digest], scenario=catalogue.scenarios[cell.key],
        package=catalogue.packages[cell.runtime_arm.content_hash]).data()['engineering_verified']
    assert snapshot() == before


def test_missing_journals_are_not_created_for_disabled_modules(tmp_path):
    root = tmp_path / 'absent'
    with pytest.raises(ContractError):
        read_m4_m5_journals(public_task('blade').identity, root)
    assert not root.exists()


@pytest.mark.parametrize('bad', [b'{"unfinished":', b'{}\r\n'])
def test_malformed_journal_remains_unchanged(tmp_path, bad):
    (tmp_path / 'predictions.jsonl').write_bytes(bad)
    (tmp_path / 'reviews.jsonl').write_bytes(b'')
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    with pytest.raises(ContractError):
        read_m4_m5_journals(public_task('blade').identity, tmp_path)
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()} == before
