import hashlib
import json
from pathlib import Path
import sys

import pytest

from research_loop.ontology import ContractError
import research_loop.modular.grok_acp_transport as acp
import research_loop.modular.grok_native_deployment as deployments
from research_loop.modular.grok_skill_isolation import isolated_config

PEER = Path(__file__).parent / 'fixtures/grok130_isolated_peer.py'
SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean', 'enum': [True]}},
          'required': ['ok'], 'additionalProperties': False}


def prepare(root, patch, mode='reload'):
    root.mkdir()
    exe = root / 'synthetic.exe'; exe.write_bytes(b'synthetic closed 130 binary pin')
    patch.setattr(deployments, 'GROK_130_SHA256', acp.digest(exe.read_bytes()))
    deployment = deployments.FrozenNativeDeployment.create(exe, skill_isolation=True)
    paths = {k: root/k for k in ('cwd', 'private_home', 'private_profile')}
    for path in paths.values(): path.mkdir()
    home = paths['private_home']; (home/'auth.json').write_bytes(b'opaque synthetic login')
    config = home/'config.toml'
    config.write_text(isolated_config(paths['cwd'], home, paths['private_profile']), encoding='utf-8')
    files = deployment.source_pins() | {str(exe): acp.digest(exe.read_bytes()),
        str(config): acp.digest(config.read_bytes()), str(PEER.resolve()): acp.digest(PEER.read_bytes()),
        str(PEER.with_name('grok_acp_peer.py').resolve()): acp.digest(PEER.with_name('grok_acp_peer.py').read_bytes())}
    original = acp.ProcessTree; launches = []
    def spawn(command, cwd, env, stderr):
        assert list(command) == deployment.command(cwd)
        assert env['GROK_DISABLE_AUTOUPDATER'] == '1'
        assert env['HOME'] == env['USERPROFILE'] == str(paths['private_profile'])
        assert not {'XAI_API_KEY', 'GROK_API_KEY', 'OPENAI_API_KEY', 'PYTHONPATH'} & set(env)
        log = root/'peer.jsonl'; launches.append(log)
        code = ('import runpy,sys;sys.path.insert(0,' + repr(str(PEER.parents[2].resolve())) + ');'
                'sys.argv=' + repr([str(PEER.resolve()), mode, str(log)]) + ';'
                'runpy.run_path(' + repr(str(PEER.resolve())) + ',run_name="__main__")')
        return original([sys.executable, '-c', code], cwd, env, stderr)
    patch.setattr(acp, 'ProcessTree', spawn)
    kwargs = dict(opportunity_contract=acp.OPPORTUNITY_CONTRACT, executable=exe, **paths,
        private_dir=root/'native', reservation=root/'reservation.json', frozen_files=files,
        prompt='synthetic bounded readiness', schema=SCHEMA, deployment=deployment, timeout=5)
    return kwargs, launches


@pytest.mark.parametrize('mode', ['reload', 'no_rpc'])
def test_real_native_entry_bundle_filter_and_exact_main_binding(tmp_path, monkeypatch, mode):
    kwargs, launches = prepare(tmp_path/'run', monkeypatch, mode)
    result = acp.run_native(**kwargs); body = result.receipt.data()
    assert body['accepted'], body
    assert body['schema'] == 'grok-native-acp-receipt-v4'
    assert body['known_usage']['totalTokens'] == 12 and body['known_usage_binding_verified']
    assert body['initial_title_usage'] is None and body['settled_additional_charge_usd'] is None
    assert len(body['internal_events']) == (mode == 'reload')
    assert body['internal_reload_is_completion_acknowledgement'] is False
    assert any(x['ignored_bundle_present'] for x in body['context_observations'])
    assert all(x['context_digest'] == body['context_digest'] for x in body['context_observations'])
    observed = json.loads(Path(str(launches[0])+'.context.json').read_bytes())
    assert observed['ordinary_skill_included'] is observed['system_reminder_injected'] is False
    raw = (kwargs['private_dir']/'stdout.private.jsonl').read_bytes()
    assert body['private_stream_sha256'] == hashlib.sha256(raw).hexdigest()
    requests = (kwargs['private_dir']/'requests.private.jsonl').read_bytes()
    assert body['request_stream_sha256'] == hashlib.sha256(requests).hexdigest()
    request_rows = [json.loads(x) for x in requests.splitlines()]
    assert [x['method'] for x in request_rows] == ['initialize','session/new','_x.ai/billing',
        '_x.ai/auto-topup-rule','session/prompt','_x.ai/billing','_x.ai/auto-topup-rule']
    assert request_rows[1]['params']['_meta']['agentProfile']['discoverSkills'] is False
    reservation = json.loads(kwargs['reservation'].read_bytes())
    assert reservation['schema'] == 'grok-acp-single-prompt-reservation-v3'
    assert reservation['context_digest'] == body['context_digest']
    if mode == 'reload':
        event = body['internal_events'][0]
        assert event['frame'] in [json.loads(x) for x in raw.splitlines()]
        assert event['frame'] == {'jsonrpc':'2.0','id':'skills-reload','result':{'result':{'reloaded':1}}}
        assert event['outstanding_request_id'] == 5 and event['session_id'] == body['session_id']


@pytest.mark.parametrize('mode,fault', [('unknown_id','rpc_binding'),('flat_result','internal_reload_shape'),
    ('bool_count','internal_reload_shape'),('two_sessions','internal_reload_shape'),
    ('extra_field','internal_reload_shape'),('error','internal_reload_shape'),
    ('early_reload','internal_reload_session_binding'),('foreign_session','session_binding'),
    ('extra_command','isolated_command_inventory'),('tools','runtime_tools_not_empty'),
    ('plugin_arrival','skill_isolation_unexpected_discovery_source'),
    ('managed_arrival','skill_isolation_unexpected_discovery_source'),('config_drift','frozen_file_changed'),
    ('no_main_result','timeout')])
def test_native_stream_keeps_closed_protocol_and_context(tmp_path, monkeypatch, mode, fault):
    kwargs, _ = prepare(tmp_path/'run', monkeypatch, mode)
    result = acp.run_native(**kwargs); body = result.receipt.data()
    assert not body['accepted'] and result.response is None
    assert fault in body['faults'], body
    assert body['initial_title_usage'] is None
    assert body['total_tokens_all_opportunities'] is None
    if mode == 'no_main_result':
        assert body['known_usage']['totalTokens'] == 12
        assert not body['known_usage_binding_verified']
        assert len(body['internal_events']) == 1


@pytest.mark.parametrize('source', ['ancestor', 'plugins', 'installed', 'profile', 'config'])
def test_context_preflight_blocks_external_sources_before_spawn(tmp_path, monkeypatch, source):
    kwargs, launches = prepare(tmp_path/'run', monkeypatch)
    home = kwargs['private_home']
    if source == 'ancestor': (tmp_path/'.agents').mkdir()
    if source == 'plugins': (home/'plugins').mkdir()
    if source == 'installed': (home/'installed-plugins').mkdir()
    if source == 'profile': (kwargs['private_profile']/'.claude').mkdir()
    if source == 'config':
        config = home/'config.toml'; config.write_text(acp.SAFE_CONFIG)
        kwargs['frozen_files'][str(config)] = acp.digest(config.read_bytes())
    with pytest.raises((ContractError, acp.Rejected)): acp.run_native(**kwargs)
    assert launches == []


def test_new_scope_cannot_enter_old_diagnostic_or_material_readers(tmp_path, monkeypatch):
    kwargs, launches = prepare(tmp_path/'run', monkeypatch)
    deployment = kwargs['deployment']
    with pytest.raises(ContractError): deployments.diagnostic_receipt_schema(deployment)
    with pytest.raises(acp.Rejected, match='isolated_readiness_only'):
        acp.run_native_diagnostic(**{k:v for k,v in kwargs.items() if k not in ('timeout','opportunity_contract')},
            opportunity_contract=acp.DIAGNOSTIC_OPPORTUNITY_CONTRACT,
            main_output_cap=512, observed_main_token_cap=20000, input_byte_cap=20000)
    from evaluation.modular.diagnostic_material_authoring import provision_native
    with pytest.raises(ContractError, match='not admitted'):
        provision_native(None, None, tmp_path/'unsupported', executable=kwargs['executable'],
            existing_auth=tmp_path/'must-not-read', deployment=deployment)
    assert not (tmp_path/'unsupported').exists() and not launches
