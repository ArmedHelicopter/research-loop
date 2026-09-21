"""Qualify public DiscoveryBench TRAIN tasks through the existing custody exporter."""
from pathlib import Path
import hashlib,json,sys,time
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from evaluation.modular.primary_prospective_exporter import PrimaryProspectiveTrainExporter,PrimaryTrainExportItem
from research_loop.ontology import digest
BASE=Path('E:/_ryanDev/AI/research-loop-modular')
SOURCE=BASE/'work/primary-prospective-export-live-r1'
SEALED=BASE/'custody-private/primary-process-split-20260913-r2'
OUT=BASE/'work/week1-domain-export-20260921-r2'
def load(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):
    with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(x,f,ensure_ascii=False,indent=2)
def main():
    OUT.mkdir()
    old=load(SOURCE/'frozen-request-r1.json')
    audit=load(SEALED/'process-audit.json')
    split=load(SEALED/'prospective-split.json')
    assert sha(SEALED/'process-audit.json')==old['audit_raw_sha256']
    assert sha(SEALED/'prospective-split.json')==old['split_raw_sha256']
    assert digest(audit)==old['audit_digest'] and digest(split)==old['split_digest']
    allocation={t:g for g in split['groups'] for t in g['member_tokens']}
    catalog=load(BASE/'work/week1-domain-diagnostic-20260921-r1/train-catalog.json')
    selected_ids={'real:test:nls_ses','real:test:worldbank_education_gdp','real:train:immigration_offshoring_effect_on_employment'}
    selected_tokens={r['token'] for r in catalog if r['task_id'] in selected_ids}
    assert len(selected_tokens)==3
    items=[PrimaryTrainExportItem(source=r['source'],token=r['token'],
           group_sha256=allocation[r['token']]['group_sha256'],input_bindings_digest=digest(audit['input_bindings']))
           for r in sorted(audit['rows'],key=lambda x:x['token'])
           if r['source']=='discoverybench' and r['token'] in selected_tokens and allocation[r['token']]['split']=='train']
    assert items
    save(OUT/'request.json',dict(schema='week1-public-train-qualification-v1',
         frozen_at=datetime.now(timezone.utc).isoformat(),rule='three preselected real social-science tasks already in frozen TRAIN; original upstream test/train names do not alter project partition; no model/scorer calls',
         items=[i.data() for i in items],split_digest=old['split_digest'],audit_digest=old['audit_digest'],
         source_script_sha256=sha(__file__),exporter_sha256=sha(ROOT/'evaluation/modular/primary_prospective_exporter.py'),
         original_request_sha256=sha(SOURCE/'frozen-request-r1.json')))
    config=load(Path(old['config_path']))
    assert sha(old['config_path'])==old['config_raw_sha256']
    exporter=PrimaryProspectiveTrainExporter(config,SEALED,
        expected_split_digest=old['split_digest'],expected_audit_digest=old['audit_digest'],
        expected_split_sha256=old['split_raw_sha256'],expected_audit_sha256=old['audit_raw_sha256'],
        eligibility_path=SOURCE/'primary-eligibility-r1.json',
        eligibility_sha256=sha(SOURCE/'primary-eligibility-r1.json'),
        output_root=OUT/'public-train',audit_root=OUT/'audit')
    started=time.monotonic()
    try:
        packets=exporter.export_packets(items)
        public=[]
        for item,packet in zip(items,packets,strict=True):
            task=packet.task
            task.identity.require_train()
            payload=task.payload.data()
            public.append(dict(token=item.token,identity=task.identity.data(),source_kind=payload.get('source_kind'),
                question=payload.get('question'),dataset=payload.get('dataset'),public_path=str(packet.packet_path),
                csv_path=str(packet.csv_path),public_sha256=sha(packet.packet_path),csv_sha256=sha(packet.csv_path)))
        save(OUT/'public-index.json',public)
        save(OUT/'result.json',dict(status='public_train_exported',tasks=len(public),
             independent_groups=len({r['identity']['group_id'] for r in public}),
             elapsed_seconds=time.monotonic()-started,model_calls=0,scorer_calls=0,validation_exports=0,
             scope='public TRAIN qualification only; no domain traces generated'))
        print(json.dumps(dict(status='public_train_exported',tasks=len(public),elapsed_seconds=time.monotonic()-started)))
    except Exception as exc:
        save(OUT/'result.json',dict(status='failed',error_type=type(exc).__name__,
             elapsed_seconds=time.monotonic()-started,model_calls=0,scorer_calls=0,validation_exports=0))
        raise
if __name__=='__main__':main()

