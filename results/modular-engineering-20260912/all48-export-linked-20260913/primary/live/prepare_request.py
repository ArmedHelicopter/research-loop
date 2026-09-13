import hashlib,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,'E:/_ryanDev/AI/research-loop-modular/primary-prospective-export')
from research_loop.ontology import digest
from evaluation.modular.fresh_airs_custodian import _write_new
project=Path('E:/_ryanDev/AI/research-loop-modular')
tree=project/'primary-prospective-export'
work=project/'work/primary-prospective-export-live-r1'
sealed=project/'custody-private/primary-process-split-20260913-r2'
def read(path):return json.loads(path.read_bytes())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()
assert head=='3558a7895de0b2369b691ab7c142a59cae6c3b15'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=tree)
root_path=project/'work/primary-seal-root-verification-r1.json'
root=read(root_path)
assert root['schema']=='primary-seal-root-metadata-verification-v1'
assert root['deterministic_partition_recomputed'] and root['audit_split_seal_digest_bindings_verified']
assert root['primary_members']==403 and root['old_train_members_all_retained']==81
assert root['declared_input_pins_verified']==24 and root['sab_validation_records_on_hold']==18
checks=project/'work/primary-prospective-export-checks'
verification=read(checks/'delivery-verification-r1.json')
assert verification['junit'][-1]['tests']==127 and not any(verification['junit'][-1][key] for key in ('failures','errors','skipped'))
source_files={row['path']:sha(tree/row['path']) for row in verification['source_files']}
assert all(source_files[row['path']]==row['current_sha256'] for row in verification['source_files'])
config_path=project/'work/primary-process-qualification-checks/primary-config-r1.json'
config=read(config_path)
assert len(config['inputs'])==24
assert all(sha(Path(row['path']))==row['sha256'] for row in config['inputs'].values())
audit=read(sealed/'process-audit.json');split=read(sealed/'prospective-split.json')
assert digest(audit)==split['audit_sha256'] and split['counts']==root['counts']
allocation={token:group for group in split['groups'] for token in group['member_tokens']}
selected=[]
for source in ('discoverybench','blade'):
    tokens=sorted(row['token'] for row in audit['rows'] if row['source']==source and row['original_train'] is True and allocation[row['token']]['split']=='train')
    assert len(tokens)>=2
    selected.extend({'source':source,'token':token,'group_sha256':allocation[token]['group_sha256'],
                     'input_bindings_digest':digest(audit['input_bindings'])} for token in tokens[:2])
request={'schema':'primary-train-export-request-v1','source_commit':head,
         'selection_rule':'original_train_true_and_new_train_per_benchmark_sorted_token_first_two',
         'items':selected,'split_digest':digest(split),'audit_digest':digest(audit),
         'split_raw_sha256':sha(sealed/'prospective-split.json'),'audit_raw_sha256':sha(sealed/'process-audit.json'),
         'config_path':str(config_path),'config_raw_sha256':sha(config_path),'root_review_sha256':sha(root_path),
         'source_verification_sha256':sha(checks/'delivery-verification-r1.json'),'source_files':source_files,
         'validation_access_enabled':False,'model_calls_authorized':False,'scorer_calls_authorized':False,'docker_calls_authorized':False}
_write_new(work/'frozen-request-r1.json',request)
eligibility={'schema':'primary-train-export-eligibility-v1','split_sha256':digest(split),'audit_sha256':digest(audit),
             'train_export_enabled':True,'held_group_sha256':[],'held_member_tokens':[],
             'review_evidence_sha256':sorted({sha(root_path),sha(checks/'delivery-verification-r1.json'),sha(checks/'source-freeze-r1.json'),
                                              request['split_raw_sha256'],request['audit_raw_sha256'],sha(work/'frozen-request-r1.json')}),
             'validation_access_enabled':False}
_write_new(work/'primary-eligibility-r1.json',eligibility)
protected=[project/'custody-private/prospective-process-split-20260913-r3/prospective-split.json',
           project/'custody-private/prospective-process-split-20260913-r3/process-audit.json',
           project/'custody-private/sab-history-eligibility-hold-20260913-r1/eligibility-hold.json',
           project/'custody-private/extended-sources/custody-inventory-v1.json']
baseline={'schema':'primary-export-before-bindings-v1','input_pins':config['inputs'],
          'protected_files':[{'path':str(path),'sha256':sha(path)} for path in protected],
          'source_files':source_files,'request_sha256':sha(work/'frozen-request-r1.json'),
          'eligibility_sha256':sha(work/'primary-eligibility-r1.json'),
          'split_raw_sha256':request['split_raw_sha256'],'audit_raw_sha256':request['audit_raw_sha256']}
_write_new(work/'before-bindings-r1.json',baseline)
print(json.dumps({'status':'request_frozen','selected_count':4,'source_counts':{'discoverybench':2,'blade':2},
                  'input_pins_verified':24,'protected_files_pinned':len(protected),'request_sha256':baseline['request_sha256'],
                  'eligibility_sha256':baseline['eligibility_sha256'],'source_commit':head,'task_payload_read':False}))
