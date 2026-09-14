import json, sys
from pathlib import Path
import pytest

import evaluation.modular.diagnostic_subscription as subscription
import research_loop.modular.grok_headless_transport as transport
from evaluation.modular.calibration_pilot_process import load_record
from tests.helpers.calibration_pilot_fixture import write
from tests.test_diagnostic_subscription import setup_subscription, unpack


def _peer(path):
    path.write_text('''import json,sys\nfrom pathlib import Path\ndef value(s):\n if "enum" in s:return s["enum"][0]\n t=s.get("type")\n if isinstance(t,list): t=next((x for x in t if x!="null"),"null")\n if t=="object": return {k:value(v) for k,v in s.get("properties",{}).items() if k in s.get("required",[])}\n if t=="array": return []\n if t=="number": return 0.0\n if t=="integer": return 0\n if t=="boolean": return False\n return "synthetic"\nif sys.argv[1]=="inspect":\n print(json.dumps({**{k:[] for k in ("skills","hooks","plugins","mcpServers","projectInstructions")},"loginPolicy":{"apiKeyAuthDisabled":True},"workflowGuide":None,"memoryDigest":None}))\nelse:\n session,prompt,schema=sys.argv[1:4]; answer=value(json.loads(schema)); usage={"input_tokens":8,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens":2,"reasoning_tokens":0}\n for row in ([{"type":"available_commands","tools":[],"commands":[]}] * 3 + [{"type":"text","data":json.dumps(answer)},{"type":"usage","usage":usage,"signature":"synthetic"},{"type":"end","stopReason":"end_turn","sessionId":session,"requestId":"synthetic-"+session,"usage":usage|{"total_tokens":10},"num_turns":1,"modelUsage":{"grok-4.6":{"inputTokens":8,"outputTokens":2,"cacheReadInputTokens":0,"cacheCreationInputTokens":0,"modelCalls":1}},"structuredOutput":answer}]): print(json.dumps(row),flush=True)\n''', encoding='utf-8')


def _run_headless_subscription(tmp_path, monkeypatch, rejection=None):
    desc, manifest, authorities, _ = setup_subscription(tmp_path / 'source', all_ready=True, main_cap=1)
    config = load_record(desc).data(); inventory = load_record(config['request_inventory']).data()
    exe = tmp_path / 'synthetic-executable'; exe.write_bytes(b'synthetic')
    monkeypatch.setattr(subscription, 'EXECUTABLE_SHA256', subscription.sha(exe))
    slots = {}; frozen = {str(p): subscription.sha(p) for p in subscription.own_sources().values()}
    frozen.update({str(Path(path)): manifest.data()['input_pins'][name]
                   for name, path in config['input_files'].items()})
    frozen[str(exe)] = subscription.sha(exe)
    for entry in inventory['entries']:
        root = tmp_path / 'native' / entry['opportunity_id']; home = root/'home'; cwd=root/'cwd'; profile=root/'profile'
        home.mkdir(parents=True); cwd.mkdir(); profile.mkdir()
        (home/'auth.json').write_text(json.dumps({'native': {'auth_mode':'oidc','oidc_issuer':'https://auth.x.ai','oidc_client_id':'b1a00492-073a-47ea-816f-4c329264a828','key':'synthetic','user_id':'synthetic-account','expires_at':'2099-01-01T00:00:00+00:00'}}))
        (home/'config.toml').write_bytes(subscription.diagnostic_config(512).encode())
        slots[entry['opportunity_id']] = {'cwd':str(cwd),'private_home':str(home),'private_profile':str(profile)}
        frozen[str(home/'config.toml')] = subscription.sha(home/'config.toml')
    deployment = write(tmp_path/'headless-deployment.json', {'schema':'frozen-native-subscription-headless-deployment-v1','executable':str(exe),'slots':slots,'frozen_files':frozen})
    config.update(schema=subscription.CONFIG_SCHEMA_V3, transport='headless', native_deployment=deployment)
    desc = write(tmp_path/'headless-config.json', config)
    peer = tmp_path/'peer.py'; _peer(peer)
    from research_loop.modular.grok_acp_transport import ProcessTree
    def spawn(command, cwd, env, stderr):
        if 'inspect' in command: args=['inspect']
        else: args=[command[command.index('--session-id')+1], command[command.index('--prompt-file')+1], command[command.index('--json-schema')+1]]
        return ProcessTree([sys.executable, str(peer), *args], cwd=cwd, env=env, stderr=stderr)
    import sys
    monkeypatch.setattr(transport, 'EXECUTABLE_SHA256', subscription.sha(exe)); monkeypatch.setattr(transport, 'ProcessTree', spawn)
    # Reuse the existing synthetic account-only opener; it never reaches a provider.
    from tests.helpers.headless_authoring_fixture import install_synthetic_native
    install_synthetic_native(monkeypatch, {'native_deployment': {'slots':slots, 'executable':str(exe)}})
    monkeypatch.setattr(transport, 'ProcessTree', spawn)
    if rejection == 'binding':
        def reject_binding(*args, **kwargs):
            raise subscription.ContractError('synthetic independent binding mismatch')
        monkeypatch.setattr(subscription, 'verify_headless_request_binding', reject_binding)
    elif rejection == 'private_request':
        original_binding = subscription.verify_headless_request_binding
        def mutate_private_request(result, entry, directory, spec, frozen_files):
            path = directory / 'headless-request.private.json'
            path.write_bytes(path.read_bytes() + b' ')
            return original_binding(result, entry, directory, spec, frozen_files)
        monkeypatch.setattr(subscription, 'verify_headless_request_binding', mutate_private_request)
    elif rejection == 'target':
        def reject_target(*args, **kwargs):
            raise subscription.ContractError('synthetic review semantic rejection')
        monkeypatch.setattr(subscription, 'target', reject_target)
    return unpack(subscription.run_private(desc), manifest, authorities)


def test_headless_subscription_ports_use_actual_producer_and_preserve_failure_denominator(tmp_path, monkeypatch):
    result = _run_headless_subscription(tmp_path, monkeypatch)
    assert result['schema'] == subscription.OBSERVATION_SCHEMA_V3
    assert result['budget']['reserved_main_opportunities'] >= 1
    record = result['budget']['records'][0]
    assert record['known_headless_main_usage']['total_tokens'] == 10
    assert record['native_accepted'] is True and record['main_binding_verified'] is True
    assert record['status'] == 'known_headless_main_expected_unknown_title'
    assert record['title_usage'] is None
    journal = [json.loads(line) for line in (tmp_path / 'source' / 'private-journal.jsonl').read_text().splitlines()]
    decisions = next(row['data']['decisions'] for row in journal if row['event'] == 'reviews_frozen')
    assert any('reviewed' in decision.get('review_statuses', []) for decision in decisions.values())
    receipt_path = next((tmp_path / 'source' / 'private-journal.jsonl.headless').glob('*/native/observer-receipt.json'))
    receipt = json.loads(receipt_path.read_text())
    assert receipt['frozen_files'][str(tmp_path / 'headless-config.json')] == subscription.sha(tmp_path / 'headless-config.json')
    assert receipt['frozen_files'][str(tmp_path / 'headless-deployment.json')] == subscription.sha(tmp_path / 'headless-deployment.json')


@pytest.mark.parametrize('rejection', ('binding', 'private_request', 'target'))
def test_headless_rejection_preserves_observed_usage_and_stops(tmp_path, monkeypatch, rejection):
    result = _run_headless_subscription(tmp_path, monkeypatch, rejection=rejection)
    budget = result['budget']
    assert budget['reserved_main_opportunities'] == 1
    assert budget['records'][0]['known_headless_main_usage']['total_tokens'] == 10
    assert budget['records'][0]['status'] == 'rejected_with_known_usage_preserved'
    assert budget['further_io_blocked'] is True


def test_closed_nullable_object_schema_accepts_object_or_null_only():
    from research_loop.modular.model_port import _validate_schema
    schema = {'type': ['object', 'null'], 'properties': {'value': {'type': 'number'}},
              'required': ['value'], 'additionalProperties': False}
    _validate_schema(schema, {'value': 0.0})
    _validate_schema(schema, None)
    with pytest.raises(subscription.ContractError):
        _validate_schema(schema, {'value': 'wrong'})
    with pytest.raises(subscription.ContractError):
        _validate_schema(schema | {'additionalProperties': True}, None)
    with pytest.raises(subscription.ContractError):
        _validate_schema(schema | {'enum': [{'value': 0.0}]}, None)
