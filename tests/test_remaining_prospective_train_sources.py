"""Closed source-mode bridge checks before actual controller integration grids."""
import pytest
from research_loop.modular.contracts import FrozenRecord
from test_admission_combination import fixture as admission_fixture, sources
from test_exploration_scheduler_combination import fixture as scheduler_fixture
from research_loop.modular.admission_combination_controller import FrozenAdmissionTrainConfig
from research_loop.modular.exploration_scheduler_controller import FrozenExplorationSchedulerTrainConfig
from research_loop.modular.q32_execution import run_q32_execution_panel


@pytest.mark.parametrize('kind', ['admission', 'scheduler'])
def test_explicit_v2_source_configuration_accepts_opaque_tokens(tmp_path, kind):
    if kind == 'admission':
        _, _, config, _, _ = admission_fixture(tmp_path, sources([]))
    else:
        _, _, config, _, _ = scheduler_fixture(tmp_path)
    body = config.data();body['schema'] = body['schema'].removesuffix('v1') + 'v2'
    body['export_mode'] = 'primary_prospective'
    body['task_bindings'] = {str(i + 1).zfill(64): binding for i, binding in enumerate(body['task_bindings'].values())}
    body['item_ids'] = list(body['task_bindings'])
    # Tokens are source handles, not labels: the actual exporter must still
    # verify them against its sealed split before any data or model use.
    actual = type(config)(FrozenRecord.from_dict(body))
    assert actual.data() == body


def test_q32_exposes_separate_typed_prospective_entry():
    from research_loop.modular.q32_execution import FrozenQ32ProspectiveConfig, run_q32_prospective_execution_panel
    assert callable(run_q32_prospective_execution_panel)
    assert FrozenQ32ProspectiveConfig is not FrozenRecord
