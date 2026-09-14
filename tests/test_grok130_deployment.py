"""Real default entry/reader plumbing, replacing only the final process spawn.

The test-local closed binary pin is substituted for a non-executable fixture;
production has no caller-supplied hash or command override.
"""
import hashlib
import json
from pathlib import Path
import sys

import pytest

import research_loop.modular.grok_acp_transport as acp
import research_loop.modular.grok_native_deployment as deployment_module
from research_loop.modular.grok_native_deployment import FrozenNativeDeployment
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError
from evaluation.modular.diagnostic_subscription import verify_native_request_binding

PEER = Path(__file__).parent / 'fixtures/grok_acp_peer.py'
SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean', 'enum': [True]}},
          'required': ['ok'], 'additionalProperties': False}


def setup_native(root, patch, mode='ok'):
    root.mkdir(parents=True, exist_ok=True)
    exe = root / 'fixture.exe'; exe.write_bytes(b'non-executable isolated 130 fixture')
    patch.setattr(deployment_module, 'GROK_130_SHA256', hashlib.sha256(exe.read_bytes()).hexdigest())
    deployment = FrozenNativeDeployment.create(exe)
    original = acp.ProcessTree; launches = []
    def spawn(command, cwd, env, stderr):
        assert list(command) == deployment.command(cwd)
        assert '--no-auto-update' not in command and env['GROK_DISABLE_AUTOUPDATER'] == '1'
        assert not {'XAI_API_KEY', 'GROK_API_KEY', 'OPENAI_API_KEY', 'PYTHONPATH'} & set(env)
        assert not list(Path(cwd).iterdir())
        config = (Path(env['GROK_HOME']) / 'config.toml').read_text()
        assert config.count('max_retries = 0') == 2
        log = root / ('peer-' + str(len(launches)) + '.jsonl'); launches.append(log)
        # Child owns an explicit test import root even though real env excludes PYTHONPATH.
        code = ('import runpy,sys;sys.path.insert(0,' + repr(str(PEER.parents[2])) + ');'
                'sys.argv=' + repr([str(PEER), mode, str(log)]) + ';'
                'runpy.run_path(' + repr(str(PEER)) + ',run_name="__main__")')
        return original([sys.executable, '-c', code], cwd, env, stderr)
    patch.setattr(acp, 'ProcessTree', spawn)
    patch.setenv('XAI_API_KEY', 'synthetic-must-not-propagate')
    return deployment, launches


def slot(root, cap=128):
    paths = {name: root/name for name in ('cwd', 'private_home', 'private_profile')}
    for path in paths.values(): path.mkdir(parents=True)
    (paths['private_home']/'auth.json').write_bytes(b'{"synthetic":true}')
    config = paths['private_home']/'config.toml'; config.write_text(acp.diagnostic_config(cap))
    return paths, config


def invoke(root, deployment, *, diagnostic=False, frozen_extra=None):
    paths, config = slot(root, 512 if diagnostic else 128)
    files = deployment.source_pins() | {deployment.executable: deployment.record.data()['executable_sha256'],
        str(config): acp.digest(config.read_bytes()), str(PEER): acp.digest(PEER.read_bytes())} | (frozen_extra or {})
    common = dict(executable=deployment.executable, **paths, private_dir=root/'native',
        reservation=root/'native-reservation.json', frozen_files=files, prompt='synthetic bounded readiness',
        schema=SCHEMA, deployment=deployment)
    if diagnostic:
        result = acp.run_native_diagnostic(**common, opportunity_contract=acp.DIAGNOSTIC_OPPORTUNITY_CONTRACT,
            main_output_cap=512, observed_main_token_cap=262144, input_byte_cap=200000)
    else:
        result = acp.run_native(**common, opportunity_contract=acp.OPPORTUNITY_CONTRACT)
    return result, files


def test_closed_production_binary_and_legacy_default_constants():
    assert deployment_module.GROK_130_SHA256 == 'ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266'
    assert acp.EXECUTABLE_SHA256 == 'bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672'
    assert acp.SAFE_CONFIG.count('max_completion_tokens = 128') == 2


@pytest.mark.parametrize('field,value', [('cli_version','future'), ('executable_sha256','a'*64),
    ('argv',['arbitrary']), ('environment',{}), ('binary_source_equivalence_verified',True)])
def test_deployment_cannot_admit_arbitrary_contract(tmp_path, field, value):
    body = FrozenNativeDeployment.create(tmp_path/'grok.exe').record.data(); body[field] = value
    with pytest.raises(ContractError): FrozenNativeDeployment(FrozenRecord.from_dict(body))


@pytest.mark.parametrize('diagnostic', [False, True])
def test_default_entry_deployment_bound_originals_and_accounting(tmp_path, monkeypatch, diagnostic):
    deployment, logs = setup_native(tmp_path/'binary',monkeypatch,mode='startup_notifications')
    root=tmp_path/'run'; result, files=invoke(root,deployment,diagnostic=diagnostic)
    body=result.receipt.data(); assert body['accepted'],body
    assert body['schema']==('grok-native-acp-diagnostic-receipt-v2' if diagnostic else 'grok-native-acp-receipt-v3')
    assert body['native_deployment']==deployment.record.data() and body['deployment_digest']==deployment.digest
    reservation=json.loads((root/'native-reservation.json').read_bytes())
    assert reservation['schema']=='grok-acp-single-prompt-reservation-v2'
    assert reservation['deployment_digest']==deployment.digest
    assert body['known_usage']['totalTokens']==12 and body['initial_title_usage'] is None
    assert body['settled_additional_charge_usd'] is None and len(logs)==1
    methods=[json.loads(line)['method'] for line in logs[0].read_text().splitlines()]
    assert methods==['initialize','session/new','_x.ai/billing','_x.ai/auto-topup-rule',
        'session/prompt','_x.ai/billing','_x.ai/auto-topup-rule']
    if diagnostic:
        entry={'prompt_sha256':acp.digest(b'synthetic bounded readiness'),'schema_digest':acp.digest(acp.encoded(SCHEMA))}
        spec={'max_input_bytes':200000,'observed_main_token_cap':262144}
        verify_native_request_binding(result,entry,root,spec,files,deployment=deployment)
        with pytest.raises(ContractError): verify_native_request_binding(result,entry,root,spec,files)
        reservation['deployment_digest']='0'*64
        (root/'native-reservation.json').write_text(json.dumps(reservation))
        # Rehash the modified reservation into a coherent original observer
        # receipt: rejection must still reach the deployment cross-binding.
        changed=body.copy();changed['diagnostic_binding']=dict(body['diagnostic_binding'])
        changed['diagnostic_binding']['reservation_sha256']=acp.digest((root/'native-reservation.json').read_bytes())
        (root/'native/observer-receipt.json').write_text(json.dumps(changed))
        rebound=acp.AcpResult(FrozenRecord.from_dict(changed),result.response)
        with pytest.raises(ContractError,match='deployment reservation'):
            verify_native_request_binding(rebound,entry,root,spec,files,deployment=deployment)


@pytest.mark.parametrize('mode', ['paid','topup','tools','model'])
def test_new_launch_keeps_preprompt_gates(tmp_path,monkeypatch,mode):
    deployment,logs=setup_native(tmp_path/'binary',monkeypatch,mode)
    result,_=invoke(tmp_path/'run',deployment)
    assert not result.receipt.data()['accepted'] and not result.receipt.data()['prompt_may_have_been_dispatched']
    assert len(logs)==1 and all(json.loads(line)['method']!='session/prompt' for line in logs[0].read_text().splitlines())


@pytest.mark.parametrize('fault',['wrong_executable','source_drift','missing_deployment_source'])
def test_new_launch_source_binding_prevents_native_spawn(tmp_path,monkeypatch,fault):
    deployment,logs=setup_native(tmp_path/'binary',monkeypatch)
    if fault=='wrong_executable':
        Path(deployment.executable).write_bytes(b'changed')
        with pytest.raises(ContractError):invoke(tmp_path/'run',deployment)
    elif fault=='source_drift':
        source=tmp_path/'source.txt';source.write_text('changed')
        result,_=invoke(tmp_path/'run',deployment,frozen_extra={str(source):'0'*64})
        assert result.receipt.data()['faults']==['frozen_file_changed']
    else:
        paths,config=slot(tmp_path/'run')
        with pytest.raises(acp.Rejected,match='deployment_source_manifest'):
            acp.native_launch(executable=deployment.executable,**paths,deployment=deployment,
                frozen_files={deployment.executable:deployment.record.data()['executable_sha256'],str(config):acp.digest(config.read_bytes())})
    assert not logs


@pytest.mark.parametrize('mode',['authoring','authoring_unknown_main'])
def test_material_v2_default_native_entry_and_original_reader(tmp_path,monkeypatch,mode):
    from tests.helpers.material_authoring_fixture import prepare_fixture
    from evaluation.modular.calibration_pilot_process import load_record
    from evaluation.modular.diagnostic_material_authoring import provision_native,run_authoring
    deployment,logs=setup_native(tmp_path/'binary',monkeypatch,mode)
    config=load_record(prepare_fixture(tmp_path/'source')).data()
    auth=tmp_path/'synthetic-login';auth.write_bytes(b'OPAQUE_SYNTHETIC_LOGIN')
    metadata=provision_native(config['publication'],config['export_result'],tmp_path/'prepared',
        executable=deployment.executable,existing_auth=auth,deployment=deployment)
    envelope=load_record(metadata['envelope']).data()
    assert envelope['schema']=='four-train-private-material-authoring-v2'
    assert envelope['native_deployment']['native']==deployment.record.data()
    assert not any(Path(p).name=='auth.json' for p in envelope['frozen_files'])
    result=run_authoring(metadata['envelope'],tmp_path/'out')
    assert result['schema']=='four-task-private-authoring-outcome-v2'
    assert result['deployment_digest']==deployment.digest
    assert len(result['authoring_outcomes'])==4 and result['slot_count']==36 and result['evaluator_opportunity_count']==72
    assert len(logs)==(4 if mode=='authoring' else 1)
    if mode=='authoring':
        assert all(r['status']=='accepted_provisional_authoring' for r in result['authoring_outcomes'])
    else:
        assert result['further_authoring_io_blocked']
        assert all(r['status']=='blocked_prior_authoring' for r in result['authoring_outcomes'][1:])
        assert result['authoring_outcomes'][0]['known_main_usage']['totalTokens']==12


@pytest.mark.parametrize('legacy_config',[False,True])
def test_subscription_v2_deployment_uses_actual_native_entry(tmp_path,monkeypatch,legacy_config):
    from test_diagnostic_subscription import setup_subscription,unpack
    from tests.helpers.calibration_pilot_fixture import write
    from evaluation.modular.calibration_pilot_process import load_record
    from evaluation.modular.diagnostic_subscription import run_private
    deployment,logs=setup_native(tmp_path/'binary',monkeypatch,'diagnostic')
    descriptor,manifest,authorities,_=setup_subscription(tmp_path/'source')
    config=load_record(descriptor).data();inventory=load_record(config['request_inventory']).data()
    files=deployment.source_pins() | {deployment.executable:deployment.record.data()['executable_sha256']}
    files.update({str(Path(p)):manifest.data()['input_pins'][name] for name,p in config['input_files'].items()})
    slots={}
    for entry in inventory['entries']:
        paths,cfg=slot(tmp_path/'slots'/entry['opportunity_id'],512)
        slots[entry['opportunity_id']]={k:str(v) for k,v in paths.items()}
        files[str(cfg)]=acp.digest(cfg.read_bytes())
    # The deployment is itself bound by the outer config descriptor. Its hash
    # joins the actual per-call source manifest after loading, avoiding a cycle.
    native=write(tmp_path/'deployment.json',{'schema':'frozen-native-subscription-deployment-v2',
        'executable':deployment.executable,'native':deployment.record.data(),'slots':slots,'frozen_files':files})
    config['native_deployment']=native
    if not legacy_config:config['schema']='diagnostic-subscription-worker-config-v2'
    descriptor=write(tmp_path/'config.json',config)
    if legacy_config:
        with pytest.raises(ContractError,match='version binding'):run_private(descriptor)
        assert not logs
        return
    result=unpack(run_private(descriptor),manifest,authorities)
    assert result['schema']=='four-train-diagnostic-subscription-observation-v2'
    assert result['native_deployment_digest']==deployment.digest
    assert result['native_deployment_descriptor']==native and result['worker_config_descriptor']==descriptor
    assert result['budget']['reserved_main_opportunities']==8 and len(logs)==8
    assert result['budget']['all_opportunity_tokens'] is None


def test_postcall_executable_drift_retains_known_main_and_terminal_receipt(tmp_path,monkeypatch):
    deployment,logs=setup_native(tmp_path/'binary',monkeypatch)
    spawn=acp.ProcessTree
    def drift_after_close(*args,**kwargs):
        tree=spawn(*args,**kwargs);close=tree.close
        def close_and_drift():
            close();Path(deployment.executable).write_bytes(b'synthetic executable drift')
        tree.close=close_and_drift
        return tree
    monkeypatch.setattr(acp,'ProcessTree',drift_after_close)
    result,_=invoke(tmp_path/'run',deployment)
    body=result.receipt.data()
    assert not body['accepted'] and 'deployment_file_changed' in body['faults']
    assert body['known_usage']['totalTokens']==12 and body['prompt_may_have_been_dispatched']
    assert body['initial_title_usage'] is None and result.response is None and len(logs)==1
