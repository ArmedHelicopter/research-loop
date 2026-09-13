"""Read-only metadata verification; no public task or reference decoding."""
import hashlib, json, sys
from pathlib import Path
BASE=Path('E:/_ryanDev/AI/research-loop-modular')
ROOT=BASE/'integration'
sys.path.insert(0,str(ROOT))
from research_loop.ontology import digest
from evaluation.modular.primary_process_qualification import partition_primary
def read(p): return json.loads(p.read_bytes())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
report=read(ROOT/'docs/primary-process-qualification-verification.json')
for row in report['artifacts']+report['junit']:
    assert sha(Path(row['path']))==row['sha256'], row['path']
for relative,value in report['source_sha256'].items():
    assert sha(ROOT/relative)==value, relative
checks=BASE/'work/primary-process-qualification-checks'
config=read(checks/'primary-config-r1.json')
for entry in config['inputs'].values():
    assert sha(Path(entry['path']))==entry['sha256']
private=BASE/'custody-private/primary-process-split-20260913-r2'
audit=read(private/'process-audit.json'); split=read(private/'prospective-split.json')
seal=read(private/'seal-receipt.json')
assert digest(audit)==seal['audit_sha256']==split['audit_sha256']==report['audit_digest']
assert digest(split)==seal['split_sha256']==report['split_digest']
groups=[{k:v for k,v in group.items() if k!='split'} for group in split['groups']]
assert partition_primary(audit,groups)==split
rows={row['token']:row for row in audit['rows']}
members=[token for group in split['groups'] for token in group['member_tokens']]
assert len(members)==len(set(members))==len(rows)==403
assert set(members)==set(rows)
for group in split['groups']:
    forced=sum(rows[token]['forced_train'] for token in group['member_tokens'])
    assert forced==group['known_train_member_count']
    assert not forced or group['split']=='train'
    assert group['source_counts']=={source:sum(rows[t]['source']==source for t in group['member_tokens']) for source in ('blade','discoverybench')}
assert sum(row['original_train'] for row in rows.values())==81
assert split['counts']=={'train':308,'validation':95}
assert sha(Path(config['inputs']['custody']['path']))==report['original_primary_custody_sha256']
hold=read(checks/'sab-eligibility-hold-r1.json')
assert hold['validation_lease_allowed'] is False and hold['held_record_count']==18
result={'schema':'primary-seal-root-metadata-verification-v1',
    'source_commit':'73a6c2d','report_and_junit_files_verified':len(report['artifacts'])+len(report['junit']),
    'declared_input_pins_verified':len(config['inputs']),'full_primary_inventory_rehashed_by_root':False,
    'production_sources_verified':len(report['source_sha256']),'deterministic_partition_recomputed':True,
    'audit_split_seal_digest_bindings_verified':True,'primary_members':len(rows),'old_train_members_all_retained':81,
    'counts':split['counts'],'source_counts':split['source_counts'],'groups':len(groups),
    'sab_validation_records_on_hold':18,'new_paid_model_calls':0,'task_or_validation_payload_decoded':False,
    'absolute_independence_established':False}
out=BASE/'work/primary-seal-root-verification-r1.json'
with out.open('x',encoding='utf-8',newline='\n') as f:
    json.dump(result,f,indent=2);f.write('\n')
print(json.dumps(result))
