"""P0 catalogue for legacy primary public TRAIN packet bytes."""
import hashlib, os
from pathlib import Path
from uuid import uuid4
from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.ontology import ContractError

CAT='legacy-primary-artifacts.jsonl'; SEAL=CAT+'.seal.json'; PACKET='packet-seal.json'; FILES=('data.csv','public.json')
def safe(p):
    p=Path(p).absolute()
    if '..' in p.parts or any(x.is_symlink() or getattr(x,'is_junction',lambda:False)() for x in (p,*p.parents)): raise ContractError('primary packet requires nonlinked paths')
    return p
def sha(raw): return hashlib.sha256(raw).hexdigest()
def sources(): return {'schema':'legacy-primary-producers-v1','exporter':source_snapshot(Path(__file__).with_name('train_io.py')),'adapter':source_snapshot(Path(__file__))}
def ref(x):
    r=FrozenRecord.from_dict(x);return {'kind':'legacy_primary_producer_sources','digest':r.content_hash,'canonical':r.data()}
def put(p,b):
    with safe(p).open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
def snapshot(p):
    b=safe(p).read_bytes();return {'file':Path(p).name,'sha256':sha(b),'bytes':len(b)}
def write(directory,task,anchor,csv,public):
    if type(task)is not PublicTask:raise ContractError('typed public task required')
    task.identity.require_train()
    if not isinstance(anchor,dict):raise ContractError('primary source anchor required')
    root=safe(directory)
    if root.exists():raise ContractError('primary packet directory already used')
    root.mkdir(parents=True);src=sources();binding=FrozenRecord.from_dict({'schema':'legacy-primary-packet-binding-v1','identity':task.identity.data(),'task_sha256':task.content_hash,'anchor':anchor,'sources':src,'train_only':True,'scientific_validated':False})
    cat=ArtifactCatalogue(root/CAT,identity=task.identity,run_id=uuid4().hex,experiment_id='P0:legacy-primary-export',lock_digest=binding.content_hash,producer_source=src['adapter']);last=cat.append(kind='p0_legacy_primary_binding',module='P0',payload=binding,config_refs=(ref(src),))
    try:
        put(root/'data.csv',csv);put(root/'public.json',public);status='produced';error=None
    except Exception as exc:status='failed';error=type(exc).__name__
    files={n:snapshot(root/n) for n in FILES if (root/n).is_file()}
    for item in files.values():last=cat.append(kind='p0_legacy_primary_file',module='P0',payload=item,parents=(last.content_hash,),config_refs=(ref(src),))
    terminal=FrozenRecord.from_dict({'schema':'legacy-primary-packet-terminal-v1','status':status,'files':files,'error_type':error,'storage_verified':True,'operation_validated':status=='produced','engineering_verified':status=='produced','scientific_validated':False})
    last=cat.append(kind='p0_legacy_primary_terminal',module='P0',payload=terminal,parents=(last.content_hash,),status=status,config_refs=(ref(src),));seal=cat.seal();packet=FrozenRecord.from_dict({'schema':'legacy-primary-train-packet-v1','binding':binding.data(),'seal':seal.data(),'train_only':True}) ;put(root/PACKET,(packet.encoded+'\n').encode())
    if status!='produced':raise ContractError('primary packet write failed')
    return verify(root,task,anchor)
def verify(directory,task,anchor):
    if type(task)is not PublicTask:raise ContractError('typed public task required')
    task.identity.require_train();root=safe(directory)
    try:p=FrozenRecord((root/PACKET).read_text().strip());b=FrozenRecord.from_dict(p.data()['binding']);first=FrozenRecord((root/CAT).read_bytes().splitlines()[0].decode()).data()['descriptor'];cat=ArtifactCatalogue(root/CAT,identity=task.identity,**first['binding']);cat.verify(FrozenRecord.from_dict(p.data()['seal']))
    except Exception as exc:raise ContractError('primary packet catalogue unreadable') from exc
    if p.data().get('schema')!='legacy-primary-train-packet-v1' or p.data().get('train_only') is not True or b.data().get('identity')!=task.identity.data() or b.data().get('task_sha256')!=task.content_hash or b.data().get('anchor')!=anchor or b.data().get('sources')!=sources():raise ContractError('primary packet binding differs')
    rows=cat.records();files={n:snapshot(root/n) for n in FILES if (root/n).is_file()};term=rows[-1].data()['payload']['canonical']
    if term.get('status')!='produced' or term.get('files')!=files or set(files)!=set(FILES) or len(rows)!=4:raise ContractError('primary packet is not a complete produced packet')
    return p
