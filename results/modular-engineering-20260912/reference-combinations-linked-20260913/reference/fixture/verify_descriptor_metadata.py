import ast, hashlib, json
from pathlib import Path
BASE=Path('E:/_ryanDev/AI/research-loop-modular')
WORK=BASE/'work/primary-reference-checks'
archive=BASE/'integration/results/modular-engineering-20260912/history-support-scorer-20260913'
script=archive/'prepare_live_train_references_20260913.py'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_bytes())
tree=ast.parse(script.read_bytes())
snapshot=None; descriptor=None
for node in tree.body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='SNAPSHOT':
        assert isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='Path'
        snapshot=Path(ast.literal_eval(node.value.args[0]))
for node in ast.walk(tree):
    if isinstance(node,ast.keyword) and node.arg=='discovery_answer_keys':
        outer=node.value
        assert isinstance(outer,ast.Dict) and len(outer.keys)==1 and ast.literal_eval(outer.keys[0])=='synth'
        values=outer.values[0]
        assert isinstance(values,ast.Dict)
        fields={ast.literal_eval(key):value for key,value in zip(values.keys,values.values,strict=True)}
        assert set(fields)=={'path','sha256','encoding'}
        path_expr=fields['path']
        assert isinstance(path_expr,ast.Call) and isinstance(path_expr.func,ast.Name) and path_expr.func.id=='str'
        path_expr=path_expr.args[0]
        assert isinstance(path_expr,ast.BinOp) and isinstance(path_expr.op,ast.Div)
        assert isinstance(path_expr.left,ast.Name) and path_expr.left.id=='SNAPSHOT'
        descriptor={'path':str(snapshot/ast.literal_eval(path_expr.right)),
                    'sha256':ast.literal_eval(fields['sha256']),'encoding':ast.literal_eval(fields['encoding'])}
assert descriptor and descriptor['encoding']=='cp1252'
status_path=archive/'train-reference-status.json'
publication_path=archive/'train-reference-publication.json'
status=read(status_path);publication=read(publication_path)
assert status['schema']=='live-train-reference-preparation-v1'
assert status['status']=='prepared_and_lookup_verified' and status['validation_items']==0
assert sha(publication_path)==status['publication_sha256']
assert publication['schema']=='train-reference-publication-v1' and publication['scope']=='train_only'
manifest_path=BASE/'custody-private/train-reference-store-20260913-01/manifest.json'
assert sha(manifest_path)==publication['manifest_sha256']
manifest=read(manifest_path)
assert manifest['schema']=='frozen-train-reference-store-v1'
assert manifest['inventory_digest']==publication['inventory_digest']
source_hashes=[source['sha256'] for row in manifest['rows'] if row['identity']['benchmark']=='discoverybench'
               for source in row['sources'] if source['role']=='answer_key']
assert source_hashes and set(source_hashes)=={descriptor['sha256']}
live=BASE/'work/primary-prospective-export-live-r1'
request=read(live/'frozen-request-r1.json')
config=read(Path(request['config_path']))
assert snapshot.resolve()==Path(config['snapshot_root']).resolve()
assert status['custody_sha256']==config['inputs']['custody']['sha256']
export_path=live/'public-train/export-receipt.json'
exports=read(export_path)
selected=[row for row in exports['packets'] if row['identity']['benchmark']=='discoverybench']
assert len(selected)==2 and all(row['official_split']=='synth/test' for row in selected)
assert all(row['identity']['domain']=='train' for row in exports['packets'])
assert all(row['identity']['dataset_version']==publication['inventory_digest'] for row in exports['packets'])
key_path=Path(descriptor['path'])
assert key_path.is_file()
report={'schema':'actual-primary-reference-descriptor-supplement-v1','status':'archived_descriptor_metadata_verified',
    'original_plan_sha256':sha(WORK/'actual-four-train-reference-plan-r1.json'),
    'discovery_answer_keys':{'synth':descriptor},'selected_discovery_count':2,'official_split':'synth/test',
    'official_source_kind':'synthetic','original_snapshot_root_matches':True,'original_inventory_digest_matches':True,
    'archived_custody_sha256_matches':True,'archived_reference_manifest_source_pin_matches':True,
    'answer_file_exists':True,'answer_file_size_bytes':key_path.stat().st_size,
    'answer_file_bytes_read_or_rehashed':False,'fresh_answer_content_pin_verification':'deferred_to_authorized_preparation_bound_reader',
    'metadata_input_pins':[{'path':str(p),'sha256':sha(p)} for p in (script,status_path,publication_path,manifest_path,
        live/'frozen-request-r1.json',export_path,Path(request['config_path']))],
    'actual_reference_preparation_executed':False,'actual_answer_reference_semantic_reads':0,
    'actual_validation_exports':0,'actual_validation_leases':0,'model_calls':0,'network_calls':0,
    'scientific_validity':'not_measured','license_qualification_claimed':False}
with (WORK/'actual-four-train-reference-descriptor-r2.json').open('x') as f:json.dump(report,f,indent=2)
print(json.dumps({'status':report['status'],'supplement_sha256':sha(WORK/'actual-four-train-reference-descriptor-r2.json'),
    'source_kind':'synthetic','encoding':descriptor['encoding'],'answer_key_sha256':descriptor['sha256'],
    'actual_answer_file_read':False,'actual_reference_preparation_executed':False}))
