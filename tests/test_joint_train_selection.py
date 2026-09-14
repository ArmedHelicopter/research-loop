"""Full-catalogue arithmetic only; actual controller integration lives separately."""
import pytest

from research_loop.modular.joint_train_selection import _rank
from research_loop.ontology import ContractError
from test_joint_train_panel import panel_fixture


def arm(panel, modules):
    return next(row['recipe']['id'] for row in panel.protocol.record.data()['catalogue']['recipes']
        if row['recipe']['id'] != 'B0'
        and {name for name, enabled in row['recipe']['arm_bits'].items() if enabled} == set(modules))


def test_negative_singletons_do_not_prune_a_positive_combination(tmp_path, monkeypatch):
    panel, _, _, logs = panel_fixture(tmp_path, monkeypatch)
    single_a, single_b, joint = (arm(panel, modules) for modules in ({'M4'}, {'M5'}, {'M4', 'M5'}))
    values = {cell.key: (1 if cell.arm_id == 'B0' else .9 if cell.arm_id == joint
              else .4 if cell.arm_id in {single_a, single_b} else .5) for cell in panel.cells}
    result = _rank(panel, values)
    assert result['selected_arm'] == joint
    effects = {row['arm_id']: row for row in result['grouped_differences']}
    assert effects[single_a]['mean_difference'] < 0 and effects[single_b]['mean_difference'] < 0
    assert effects[joint]['mean_difference'] == pytest.approx(.4)
    assert set(effects) == set(panel.protocol.record.data()['selection_rule']['tie_break_order'])
    assert len(effects) == 58 and 'B0' not in effects and not logs


def test_equal_benchmark_weight_and_per_benchmark_regression_guard(tmp_path, monkeypatch):
    panel, _, _, logs = panel_fixture(tmp_path, monkeypatch)
    joint = arm(panel, {'M4', 'M5'})
    values = {cell.key: (.5 if cell.arm_id in {'ordinary-control', 'B0'} else
              (1 if cell.identity.benchmark == 'discoverybench' else .4) if cell.arm_id == joint else .3)
              for cell in panel.cells}
    result = _rank(panel, values)
    effect = next(row for row in result['grouped_differences'] if row['arm_id'] == joint)
    # Two Discovery groups and one BLADE group: each benchmark gets half weight.
    assert effect['mean_difference'] == pytest.approx(.2)
    assert effect['eligible_for_train_selection'] is False
    assert result['selected_arm'] == 'ordinary-control' and not logs


def test_ties_follow_the_precommitted_order(tmp_path, monkeypatch):
    panel, _, _, logs = panel_fixture(tmp_path, monkeypatch)
    result = _rank(panel, {cell.key: .5 for cell in panel.cells})
    assert result['selected_arm'] == panel.protocol.record.data()['selection_rule']['tie_break_order'][0]
    assert not logs


@pytest.mark.parametrize('fault', ['missing_b0', 'extra', 'nan', 'infinite', 'boolean', 'out_of_range'])
def test_incomplete_or_invalid_scores_cannot_enter_ranking(tmp_path, monkeypatch, fault):
    panel, _, _, logs = panel_fixture(tmp_path, monkeypatch)
    values = {cell.key: .5 for cell in panel.cells}
    if fault == 'missing_b0':
        values.pop(next(cell.key for cell in panel.cells if cell.arm_id == 'B0'))
    elif fault == 'extra':
        values[('foreign',)] = .5
    else:
        values[panel.cells[0].key] = {'nan': float('nan'), 'infinite': float('inf'),
                                    'boolean': True, 'out_of_range': 1.1}[fault]
    with pytest.raises(ContractError):
        _rank(panel, values)
    assert not logs
