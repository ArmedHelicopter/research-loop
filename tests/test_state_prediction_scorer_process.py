"""Closed subprocess configuration checks for the three state-prediction pairs."""
import hashlib
import os
from pathlib import Path
import sys

import pytest

from evaluation.modular.scorer_process import (CombinationScorerProcessClient, parse_combination_panel,
    parse_server_config, serialize_combination_panel)
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical
from test_modular_combination_train_controller import EXECUTION, SCORER
from test_scorer_process import _store
from test_state_prediction_combination_driver import DESIGNS, _panel


def _server(root: Path, panel, packets):
    root.mkdir(parents=True)
    store, handles, manifest_sha = _store(root, {"tasks": {p.task.content_hash: p.task for p in packets}})
    execution, scorer = root / "execution.key", root / "scorer.key"
    execution.write_bytes(EXECUTION.key)
    scorer.write_bytes(SCORER.key)
    # The score configuration itself is supplied by the controller; this helper
    # deliberately only proves the independent process accepts the frozen scope.
    from evaluation.modular.scoring_service import ScorerConfig
    config = ScorerConfig.create(benchmark="core_pair", evaluator_id="synthetic-lineage-rubric", version="v1",
        rubric_digest=FrozenRecord.from_dict({"fixture_rubric": ["a", "b"]}).content_hash)
    if config.digest != next(iter(panel.cells)).scorer_digest:
        # The upstream fixture deliberately pins its two synthetic rubric endpoints.
        from test_lineage_combination_controller import ENDPOINTS
        config = ScorerConfig.create(benchmark="core_pair", evaluator_id="synthetic-lineage-rubric", version="v1",
            rubric_digest=FrozenRecord.from_dict({"fixture_rubric": list(ENDPOINTS)}).content_hash)
    assert config.digest == next(iter(panel.cells)).scorer_digest
    body = {"schema": "state-prediction-scorer-process-config-v1",
        "panel": serialize_combination_panel(panel, state_prediction=True),
        "scorer_config": config.record.data(), "scorer_config_digest": config.digest,
        "train_reference_store": {"root": str(store.resolve()), "manifest_sha256": manifest_sha,
            "inventory_digest": packets[0].task.identity.dataset_version, "split_digest": panel.split_digest},
        "task_handles": handles, "execution_authority_key_files": {EXECUTION.authority_id: str(execution.resolve())},
        "scorer_authority": {"id": SCORER.authority_id, "key_file": str(scorer.resolve())},
        "evaluator": {"synthetic_mode": "normal"}}
    return body, config, handles


def test_exact_state_prediction_scope_roundtrips_all_registered_pairs(tmp_path):
    assert set(DESIGNS) == {"pair:M1+M4", "pair:M2+M4", "pair:M3+M4"}
    for number, obligation in enumerate(DESIGNS):
        panel, packets, *_ = _panel(tmp_path / str(number), obligation)
        encoded = serialize_combination_panel(panel, state_prediction=True)
        assert encoded["panel_digest"] == panel.digest
        assert parse_combination_panel(encoded, state_prediction=True) == panel
        body, _, _ = _server(tmp_path / ("server-" + str(number)), panel, packets)
        parsed = parse_server_config(body)
        assert parsed.panel == panel and parsed.scorer.digest == panel.cells[0].scorer_digest


@pytest.mark.parametrize("flags", [
    {"state_prediction": 1}, {"state_prediction": "false"},
    {"state_prediction": True, "lineage": True},
    {"state_prediction": True, "retrieval_review": True},
    {"state_prediction": True, "admission": True},
    {"state_prediction": True, "exploration_scheduler": True},
])
def test_state_prediction_scope_cannot_be_coerced_or_mixed(tmp_path, flags):
    panel, *_ = _panel(tmp_path, "pair:M1+M4")
    with pytest.raises(ContractError, match="one strict explicit scope"):
        serialize_combination_panel(panel, **flags)


def test_actual_state_prediction_worker_handshake_binds_one_declared_pair(tmp_path):
    panel, packets, *_ = _panel(tmp_path / "panel", "pair:M2+M4")
    body, config, handles = _server(tmp_path / "server", panel, packets)
    path = tmp_path / "server.json"
    path.write_text(canonical(body), encoding="utf-8")
    helper = Path(__file__).parent / "helpers" / "state_prediction_scorer_process_helper.py"
    client = CombinationScorerProcessClient(panel=panel, config=config, state_prediction=True,
        command=[sys.executable, str(helper.resolve()), "--config", str(path.resolve()),
            "--config-sha256", hashlib.sha256(path.read_bytes()).hexdigest(), "--journal", str((tmp_path / "worker.jsonl").resolve())],
        journal_path=tmp_path / "client.jsonl",
        task_handle_bindings={key: hashlib.sha256(value.encode()).hexdigest() for key, value in handles.items()},
        execution_authority_keys={EXECUTION.authority_id: EXECUTION.key}, scorer_authority_keys={SCORER.authority_id: SCORER.key},
        environment={**os.environ, "PYTHONIOENCODING": "gbk"})
    try:
        assert client.binding.data()["panel_digest"] == panel.digest
        assert client.state_prediction is True
        assert not (tmp_path / "worker.jsonl").exists()
    finally:
        client.close()
