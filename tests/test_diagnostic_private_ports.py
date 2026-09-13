"""Real local HTTP transport, synthetic private references only."""
from pathlib import Path
import pytest

from evaluation.modular.diagnostic_private_ports import (
    PrivateRequestRenderer, FrozenHTTPDeployment, PrivateHTTPPorts,
)
from evaluation.modular.calibration_pilot import blind_request
from evaluation.modular.reference_store import FrozenTrainReferenceResolver
from research_loop.ontology import ContractError
from tests.helpers.calibration_pilot_fixture import build_fixture, record


def setup_renderer(tmp_path):
    manifest, materials, authorities, config = build_fixture(tmp_path)
    store = config.data()['reference_store']
    resolver = FrozenTrainReferenceResolver(Path(store['root']), manifest_sha256=store['manifest_sha256'],
        inventory_digest=store['inventory_digest'], split_digest=store['split_digest'])
    return PrivateRequestRenderer(manifest, resolver), manifest, materials, authorities, config


def test_renderer_resolves_train_reference_and_blinds_labels(tmp_path):
    renderer, manifest, materials, _, _ = setup_renderer(tmp_path)
    slot = manifest.data()['slots'][0]
    task = manifest.data()['tasks'][0]
    request = blind_request(manifest, slot, task, materials[slot['slot_id']]['body']['payload'])
    rendered = renderer.render('reviewer1', request)
    assert 'PRIVATE_SYNTHETIC_REFERENCE_SENTINEL' in rendered.encoded
    assert 'support_digest' not in rendered.encoded and '"expected"' not in rendered.encoded
    assert '"kind"' not in rendered.encoded and '"slot_token"' in rendered.encoded


def test_foreign_handle_rejected_before_resolver_payload_read(tmp_path, monkeypatch):
    renderer, manifest, materials, _, _ = setup_renderer(tmp_path)
    slot = manifest.data()['slots'][0]; task = manifest.data()['tasks'][0]
    request = blind_request(manifest, slot, task, materials[slot['slot_id']]['body']['payload']).data()
    request['task_handle'] = 'f' * 64
    calls = []
    monkeypatch.setattr(FrozenTrainReferenceResolver, '__call__', lambda *args: calls.append(args))
    with pytest.raises(ContractError):
        renderer.render('reviewer1', record(request))
    assert calls == []
