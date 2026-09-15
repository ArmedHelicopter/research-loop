"""C5 native-stdio seam: synthetic TRAIN records only, no C5 runtime experiment."""
from contextlib import ExitStack
import copy
import hashlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from evaluation.modular.scorer_process import CombinationScorerProcessClient, headless_evaluator_descriptor, serialize_combination_panel
from research_loop.modular.joint_train_controller import _finalize_headless_c5_evaluator
from research_loop.modular.joint_train_evaluator_verification import verify_joint_headless_evaluator_gate
from research_loop.ontology import ContractError, canonical
from test_headless_evaluator_factory import native_spec
from test_joint_train_panel import panel_fixture, synthetic_signed_input
from test_scorer_process import _store
from test_train_adapted_selection import EXEC, SCORER


def _server(root, panel, args, evaluator):
    """Build the actual C5 worker configuration around synthetic fixture inputs."""
    store, handles, manifest = _store(root, {"tasks": {task.content_hash: task for task in args["targets"]}})
    execution_key, scorer_key = root / "execution.key", root / "scorer.key"
    execution_key.write_bytes(EXEC.key)
    scorer_key.write_bytes(SCORER.key)
    body = {"schema": "c5-common-train-scorer-process-config-v1",
        "panel": serialize_combination_panel(panel, joint_train=True),
        "scorer_config": args["scorer"].record.data(), "scorer_config_digest": args["scorer"].digest,
        "train_reference_store": {"root": str(store.resolve()), "manifest_sha256": manifest,
            "inventory_digest": panel.cells[0].identity.dataset_version, "split_digest": panel.split_digest},
        "task_handles": handles,
        "execution_authority_key_files": {EXEC.authority_id: str(execution_key)},
        "scorer_authority": {"id": SCORER.authority_id, "key_file": str(scorer_key)},
        "evaluator": evaluator}
    path = root / "scorer-server.json"
    path.write_text(canonical(body), encoding="utf-8")
    return path, handles


def _client(*, root, panel, scorer, server_path, handles, provider):
    helper = Path(__file__).parent / "helpers" / "headless_c5_evaluator_process.py"
    return CombinationScorerProcessClient(panel=panel, config=scorer, joint_train=True,
        command=[sys.executable, str(helper.resolve()), "--config", str(server_path.resolve()),
                 "--config-sha256", hashlib.sha256(server_path.read_bytes()).hexdigest(),
                 "--journal", str((root / "worker.jsonl").resolve())],
        journal_path=root / "client.jsonl",
        task_handle_bindings={key: hashlib.sha256(value.encode()).hexdigest() for key, value in handles.items()},
        execution_authority_keys={EXEC.authority_id: EXEC.key}, scorer_authority_keys={SCORER.authority_id: SCORER.key},
        evaluator_provider=provider, environment={**os.environ, "PYTHONIOENCODING": "utf-8"})


def test_c5_headless_stdio_binds_descriptor_and_retains_signed_closure(tmp_path, monkeypatch):
    """The canonical 177-cell scorer panel checks the seam, not a C5 runtime experiment."""
    panel_root = tmp_path / "panel"; panel_root.mkdir()
    panel, args, _, logs = panel_fixture(panel_root, monkeypatch)
    assert len(panel.cells) == 177
    with pytest.MonkeyPatch.context() as native_patch:
        evaluator, _, _ = native_spec(tmp_path / "evaluator", native_patch)
    scorer_body = args["scorer"].record.data()
    evaluator_root = tmp_path / "worker-evaluator"
    evaluator_root.mkdir(); (evaluator_root / "home").mkdir()
    evaluator.update(max_calls=len(panel.cells), max_tokens=len(panel.cells) * 100,
                     evaluator_id=scorer_body["evaluator_id"], evaluator_version=scorer_body["version"],
                     work_root=str(evaluator_root / "ledger"), private_home=str(evaluator_root / "home"),
                     private_profile=str(evaluator_root / "profile"), public_cwd=str(evaluator_root / "context"))
    descriptor = headless_evaluator_descriptor(evaluator)
    provider = {"kind": "grok-headless-frozen-evaluator-v1", "configuration_digest": descriptor["configuration_digest"]}
    usage = {"schema": "c5-headless-evaluator-usage-declaration-v1",
        "provider_kind": provider["kind"], "usage_contract": "grok-headless-c5-usage-v1",
        "evaluator_config_digest": provider["configuration_digest"]}
    server_path, handles = _server(tmp_path, panel, args, evaluator)

    with ExitStack() as stack:
        client = _client(root=tmp_path, panel=panel, scorer=args["scorer"], server_path=server_path,
                         handles=handles, provider=provider)
        stack.callback(client.close)
        scores = [client.score_combination(panel=panel, cell=cell, score_input=synthetic_signed_input(panel, cell))
                  for cell in panel.cells]
        plan = SimpleNamespace(headless_evaluator_binding={"evaluator_usage": usage, "evaluator_provider": provider},
            protocol=SimpleNamespace(record=type(args["scorer"].record).from_dict({"scorer": scorer_body})))
        gate = _finalize_headless_c5_evaluator(plan=plan, panel=panel, service=client, scores=tuple(scores),
            scorer_authority_keys={SCORER.authority_id: SCORER.key})
        closure = client.final_closure
        verified = verify_joint_headless_evaluator_gate(gate,
            authority_keys={SCORER.authority_id: SCORER.key}, panel=panel, scorer_config=args["scorer"],
            evaluator_provider=provider, evaluator_usage=usage,
            ordered_receipt_digests=tuple(score.receipt.content_hash for score in scores))
        assert closure is not None and gate["closure"] == closure.data()
        assert verified.data()["known_main_tokens"] == len(panel.cells) * 10
        assert verified.data()["scope"]["unscored_cell_count"] == 0

        tampered = copy.deepcopy(gate)
        tampered["closure"]["mac"] = "0" * 64
        with pytest.raises(ContractError):
            verify_joint_headless_evaluator_gate(tampered,
                authority_keys={SCORER.authority_id: SCORER.key}, panel=panel, scorer_config=args["scorer"],
                evaluator_provider=provider, evaluator_usage=usage,
                ordered_receipt_digests=tuple(score.receipt.content_hash for score in scores))

    # The worker reports the actual production factory descriptor, so a caller
    # cannot relabel the worker with an unrelated declaration during startup.
    bad = {**provider, "configuration_digest": "0" * 64}
    with pytest.raises(ContractError, match="startup binding differs"):
        _client(root=tmp_path / "mismatch", panel=panel, scorer=args["scorer"], server_path=server_path,
                handles=handles, provider=bad)

    import json
    ledger = json.loads((Path(evaluator["work_root"]) / "ledger.json").read_text(encoding="utf-8"))
    assert len(ledger["calls"]) == len(panel.cells)
    assert ledger["known_main_tokens"] == len(panel.cells) * 10
    assert not logs
    assert "PRIVATE-REFERENCE-SENTINEL" not in (tmp_path / "client.jsonl").read_text(encoding="utf-8")
    assert "PRIVATE-REFERENCE-SENTINEL" not in (tmp_path / "worker.jsonl").read_text(encoding="utf-8")
