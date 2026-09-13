import contextlib, hashlib, io, json, subprocess, sys
from pathlib import Path
BASE=Path('E:/_ryanDev/AI/research-loop-modular')
TREE=BASE/'pr-ref'
WORK=BASE/'work/primary-prospective-reference-live-r1'
CHECKS=BASE/'work/primary-reference-checks'
EXPORT=BASE/'work/primary-prospective-export-live-r1'
STORE=BASE/'custody-private/primary-prospective-train-reference-20260913-r1'
AUDIT=BASE/'custody-private/primary-prospective-reference-audit-20260913-r1'
SEALED=BASE/'custody-private/primary-process-split-20260913-r2'
sys.path.insert(0,str(TREE))
from evaluation.modular.fresh_airs_custodian import _write_new
from evaluation.modular.prospective_train_exporter import _concrete
from research_loop.ontology import digest

def sha(path):return hashlib.sha256(_concrete(path).read_bytes()).hexdigest()
def read(path):return json.loads(_concrete(path).read_bytes())
def main():
    assert not STORE.exists() and not AUDIT.exists()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
    assert head=='e573bf75f404715dfadbce7b461e78a41ddd88f9'
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=TREE)
    pins={CHECKS/'actual-four-train-reference-plan-r1.json':'5e6a79bc55c1385b25f7eb73b61381adffb1a085d6a20b0c9ea68931e7208818',
          CHECKS/'actual-four-train-reference-descriptor-r2.json':'53b849053d87eb81565c16440f53c2460f800e9bdbbc1e0d568ee47445669f3e',
          EXPORT/'frozen-request-r1.json':'8713df0bccbd7dfd499e4461790bb5c983fe0b89b37d3eac98867df250cb6685',
          CHECKS/'delivery-verification-r1.json':'bb910360b95de7f2ad7d45e2c4452104f073a58179c952213ea2a34fa5282f8d',
          CHECKS/'frozen-r1.xml':'3962344becb69cdbaf23ff9435afe11d6bcade125110986388981d6f5474418f',
          CHECKS/'source-freeze-r1.json':'f074589326fee7ef97e065713e9f3846232f136bb4b05e96f2a35cfbd5a89706'}
    assert all(sha(path)==value for path,value in pins.items())
    plan=read(CHECKS/'actual-four-train-reference-plan-r1.json')
    descriptor=read(CHECKS/'actual-four-train-reference-descriptor-r2.json')
    original=read(EXPORT/'frozen-request-r1.json')
    before=read(EXPORT/'before-bindings-r1.json')
    config=read(Path(original['config_path']))
    source_files=read(CHECKS/'source-freeze-r1.json')['files']
    assert all(sha(TREE/path)==value for path,value in source_files.items())
    assert [row['item'] for row in plan['requests']]==original['items'] and len(plan['requests'])==4
    assert [row['item']['source'] for row in plan['requests']]==['discoverybench','discoverybench','blade','blade']
    assert descriptor['discovery_answer_keys']['synth']['sha256']=='afd51d7053cefff6b335c209a42a1943217cb73a9fd36144a500cce49ecda675'
    assert descriptor['discovery_answer_keys']['synth']['encoding']=='cp1252'
    assert len(config['inputs'])==24 and config['inputs']==before['input_pins']
    assert all(sha(Path(row['path']))==row['sha256'] for row in config['inputs'].values())
    for row in descriptor['metadata_input_pins']:
        assert sha(Path(row['path']))==row['sha256'];pins[Path(row['path'])]=row['sha256']
    for row in before['protected_files']:
        assert sha(Path(row['path']))==row['sha256'];pins[Path(row['path'])]=row['sha256']
    pins[SEALED/'process-audit.json']=original['audit_raw_sha256']
    pins[SEALED/'prospective-split.json']=original['split_raw_sha256']
    pins[SEALED/'seal-receipt.json']=sha(SEALED/'seal-receipt.json')
    for name in ('primary-eligibility-r1.json','before-bindings-r1.json','after-bindings-r1.json',
                 'actual-result-r1.json','delivery-manifest-r1.json','export-audit/exports.jsonl'):
        pins[EXPORT/name]=sha(EXPORT/name)
    assert pins[EXPORT/'export-audit/exports.jsonl']=='0a99c347e1a1f255efb5ca753d9ff7ad67574cd2887bc82d19cf4711e7b3737b'
    pins[EXPORT/'public-train/export-receipt.json']=plan['frozen_public_receipt']['sha256']
    for row in plan['requests']:
        root=EXPORT/'public-train'/row['item']['token']
        for name,key in (('public.json','public_sha256'),('data.csv','csv_sha256'),('receipt.json','receipt_sha256')):
            pins[root/name]=row[key]
    assert all(sha(path)==value for path,value in pins.items())
    request={'schema':'actual-primary-reference-request-v1','source_commit':head,'source_files':source_files,
        'requests':plan['requests'],'discovery_answer_keys':descriptor['discovery_answer_keys'],
        'source_pins':config['inputs'],'protected_pins':[{'path':str(path),'sha256':value} for path,value in sorted(pins.items())],
        'config_path':original['config_path'],'config_sha256':original['config_raw_sha256'],
        'split_digest':original['split_digest'],'audit_digest':original['audit_digest'],
        'split_raw_sha256':original['split_raw_sha256'],'audit_raw_sha256':original['audit_raw_sha256'],
        'eligibility_path':str(EXPORT/'primary-eligibility-r1.json'),'eligibility_sha256':pins[EXPORT/'primary-eligibility-r1.json'],
        'export_root':str(EXPORT/'public-train'),'export_audit_root':str(EXPORT/'export-audit'),
        'export_receipt_sha256':plan['frozen_public_receipt']['sha256'],
        'store_root':str(STORE),'audit_root':str(AUDIT),'sealed_root':str(SEALED),
        'attempt_limit':1,'selection_rule':original['selection_rule'],'validation_access_enabled':False,
        'model_calls_authorized':False,'scorer_calls_authorized':False,'docker_calls_authorized':False,'network_calls_authorized':False,
        'authorization_scope':'root_explicit_fixed_four_train_reference_preparation_and_standard_resolver_check',
        'freeze_script_sha256':sha(Path(__file__))}
    _write_new(WORK/'frozen-reference-request-r1.json',request)
    _write_new(WORK/'before-pins-r1.json',{'schema':'actual-primary-reference-before-pins-v1','source_commit':head,
        'source_files':source_files,'source_pins':config['inputs'],'protected_pins':request['protected_pins'],
        'request_sha256':sha(WORK/'frozen-reference-request-r1.json')})
    return {'status':'frozen','request_sha256':sha(WORK/'frozen-reference-request-r1.json'),
        'source_commit':head,'source_files_verified':len(source_files),'source_inputs_verified':24,
        'protected_files_verified':len(pins),'train_items':4,'reference_payload_reads':0}

if __name__=='__main__':
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):result=main()
    except BaseException:
        result={'status':'freeze_failed','error':'contract_or_io_failure','reference_preparation_attempted':False}
        _write_new(WORK/'freeze-failure-r1.json',result)
    print(json.dumps(result))
