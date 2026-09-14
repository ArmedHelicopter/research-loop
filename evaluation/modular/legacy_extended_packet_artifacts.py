"""P0 evidence for public-only legacy extended TRAIN packets."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.ontology import ContractError

_CAT='legacy-extended-artifacts.jsonl'; _CAT_SEAL=_CAT+'.seal.json'; _SEAL='packet-seal.json'
_PUBLIC=('public.json','receipt.json'); _ALL={*_PUBLIC,_CAT,_CAT_SEAL,_SEAL}

def _safe(path):
    if '..' in Path(path).parts: raise ContractError('legacy packet paths must not traverse parents')
    path=Path(path).absolute()
    if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in (path,*path.parents)): raise ContractError('legacy packet paths must not use links')
    return path
def _sha(raw): return hashlib.sha256(raw).hexdigest()
def _sources():
    return {'schema':'legacy-extended-packet-producers-v1','exporter':source_snapshot(Path(__file__).with_name('extended_ingestion.py')),'adapter':source_snapshot(Path(__file__))}
def _ref(value):
    record=FrozenRecord.from_dict(value);return {'kind':'legacy_extended_producer_sources','digest':record.content_hash,'canonical':record.data()}
def _new(path,raw):
    with _safe(path).open('xb') as stream: stream.write(raw);stream.flush();os.fsync(stream.fileno())
def _snapshot(path):
    raw=_safe(path).read_bytes();return {'file':Path(path).name,'sha256':_sha(raw),'bytes':len(raw)}
def _files(root,partial=False,complete=True):
    root=_safe(root)
    if not root.is_dir(): raise ContractError('legacy packet directory is unavailable')
    paths=list(root.iterdir())
    if any(not _safe(p).is_file() or p.name not in _ALL for p in paths): raise ContractError('legacy packet has an unregistered output')
    names={p.name for p in paths}
    required={_CAT} if not complete else {_CAT,_CAT_SEAL,_SEAL}
    if not required<=names or complete and not partial and names!=_ALL: raise ContractError('legacy packet output inventory differs')
    return {name:_snapshot(root/name) for name in _PUBLIC if (root/name).is_file()}

class LegacyExtendedPacketArtifacts:
    def __init__(self,directory,task,source_sha256):
        if type(task)is not PublicTask: raise ContractError('legacy packet requires an exact public task')
        task.identity.require_train()
        if not isinstance(source_sha256,str) or len(source_sha256)!=64 or any(c not in '0123456789abcdef' for c in source_sha256): raise ContractError('legacy packet requires a train source digest')
        self.root,self.task,self.source_sha256=_safe(directory),task,source_sha256
        if self.root.exists(): raise ContractError('legacy packet directory already used')
        self.root.mkdir(parents=True,exist_ok=False);self.sources=_sources();self.done=False;self.stage='reservation'
        self.binding=FrozenRecord.from_dict({'schema':'legacy-extended-packet-binding-v2','identity':task.identity.data(),'task_sha256':task.content_hash,'source_sha256':source_sha256,'scope':'train_only','raw_private_payload_returned':False,'producer_sources':self.sources,'scientific_validated':False})
        self.catalogue=ArtifactCatalogue(self.root/_CAT,identity=task.identity,run_id=uuid4().hex,experiment_id='P0:legacy-extended-export',lock_digest=self.binding.content_hash,producer_source=self.sources['adapter'])
        self.last=self.catalogue.append(kind='p0_legacy_extended_binding',module='P0',payload=self.binding,config_refs=(_ref(self.sources),))
    def write(self,public,receipt):
        try:
            self.stage='public';_new(self.root/'public.json',public)
            self.stage='receipt';_new(self.root/'receipt.json',receipt)
            self.stage='seal';return self._finish('produced')
        except Exception as error:
            try: self.fail(error)
            except Exception as closure_error:
                error.add_note('legacy packet failure closure also failed: '+type(closure_error).__name__)
            raise
    def _finish(self,status,error_type=None):
        if self.done: raise ContractError('legacy packet already sealed')
        files=_files(self.root,partial=True,complete=False)
        for snapshot in files.values(): self.last=self.catalogue.append(kind='p0_legacy_extended_file',module='P0',payload=snapshot,parents=(self.last.content_hash,),config_refs=(_ref(self.sources),))
        terminal=FrozenRecord.from_dict({'schema':'legacy-extended-packet-terminal-v2','status':status,'files':files,
            'stage':'complete' if status=='produced' else self.stage,'error_type':error_type,
            'raw_private_payload_returned':False,'scientific_validated':False})
        self.last=self.catalogue.append(kind='p0_legacy_extended_terminal',module='P0',payload=terminal,parents=(self.last.content_hash,),status=status,config_refs=(_ref(self.sources),))
        seal=self.catalogue.seal();packet=FrozenRecord.from_dict({'schema':'legacy-extended-train-packet-v2','binding':self.binding.data(),'catalogue_seal':seal.data(),'raw_private_payload_returned':False,'scope':'train_only'})
        _new(self.root/_SEAL,(packet.encoded+'\n').encode());self.done=True;return packet
    def fail(self,error):
        if not self.done:self._finish('failed',type(error).__name__)

def seal_packet(directory,task,source_sha256,public,receipt): return LegacyExtendedPacketArtifacts(directory,task,source_sha256).write(public,receipt)

def verify_packet(directory,task,expected_source_sha256=None):
    """Read only public outputs; failed packets never validate an operation."""
    if type(task)is not PublicTask: raise ContractError('legacy packet reader requires an exact public task')
    task.identity.require_train()
    if not isinstance(expected_source_sha256,str) or len(expected_source_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_source_sha256): raise ContractError('legacy packet reader requires its expected train source digest')
    root=_safe(directory)
    _files(root,partial=True)  # Validate every path before opening seal-supplied data.
    try: packet=FrozenRecord((root/_SEAL).read_text(encoding='utf-8').strip());body=packet.data();binding=FrozenRecord.from_dict(body['binding']);b=binding.data()
    except (OSError,UnicodeError,KeyError,ValueError,ContractError) as exc: raise ContractError('legacy packet seal is unreadable') from exc
    required_binding={'schema','identity','task_sha256','source_sha256','scope','raw_private_payload_returned','producer_sources','scientific_validated'}
    if (set(body)!={'schema','binding','catalogue_seal','raw_private_payload_returned','scope'} or body['schema']!='legacy-extended-train-packet-v2' or body['scope']!='train_only' or body['raw_private_payload_returned'] is not False or set(b)!=required_binding or b['schema']!='legacy-extended-packet-binding-v2' or b['identity']!=task.identity.data() or b['task_sha256']!=task.content_hash or b['scope']!='train_only' or b['raw_private_payload_returned'] is not False or b['scientific_validated'] is not False or b['source_sha256']!=expected_source_sha256 or b['producer_sources']!=_sources()): raise ContractError('legacy packet subject or source binding differs')
    try:
        first=FrozenRecord((root/_CAT).read_bytes().splitlines()[0].decode()).data()['descriptor'];binding_fields=first['binding'];cat=ArtifactCatalogue(root/_CAT,identity=task.identity,**binding_fields);cat.verify(FrozenRecord.from_dict(body['catalogue_seal']))
    except (IndexError,KeyError,UnicodeError,ValueError,ContractError) as exc: raise ContractError('legacy packet catalogue differs') from exc
    records=cat.records()
    if (binding_fields.get('experiment_id')!='P0:legacy-extended-export' or binding_fields.get('lock_digest')!=binding.content_hash or not isinstance(binding_fields.get('run_id'),str) or len(binding_fields['run_id'])!=32 or any(c not in '0123456789abcdef' for c in binding_fields['run_id']) or not records or records[0].data()['payload']['canonical']!=b): raise ContractError('legacy packet catalogue lacks its original reservation')
    terminal=records[-1].data();value=terminal['payload']['canonical'];status=value.get('status')
    files=_files(root,partial=status=='failed')
    if status=='produced':
        stage,error_type='complete',None
    else:
        stage,error_type=value.get('stage'),value.get('error_type')
        if (stage not in {'public','receipt','seal'} or type(error_type)is not str or not error_type
                or stage=='public' and 'receipt.json' in files
                or stage in {'receipt','seal'} and 'public.json' not in files
                or stage=='seal' and 'receipt.json' not in files):
            raise ContractError('legacy packet failure stage differs from retained output prefix')
    expected={'schema':'legacy-extended-packet-terminal-v2','status':status,'files':files,
        'stage':stage,'error_type':error_type,'raw_private_payload_returned':False,'scientific_validated':False}
    reference=_ref(b['producer_sources']); previous=None
    if len(records)!=len(files)+2: raise ContractError('legacy packet descriptor count differs')
    for index,record in enumerate(records):
        row=record.data(); expected_kind='p0_legacy_extended_binding' if index==0 else 'p0_legacy_extended_terminal' if index==len(records)-1 else 'p0_legacy_extended_file'
        expected_payload=b if index==0 else expected if index==len(records)-1 else list(files.values())[index-1]
        expected_status=status if index==len(records)-1 else 'produced'
        if (row['kind']!=expected_kind or row['module']!='P0' or row['coverage']!='covered' or row['status']!=expected_status
                or row['parents']!=([] if previous is None else [previous]) or row['producer_source']!=b['producer_sources']['adapter']
                or row['config_refs']!=[reference] or row['checks']!=[] or row['cost']!={'known':False,'units':None}
                or row['optimizer_visible'] is not False or row['scientific_validated'] is not False
                or FrozenRecord.from_dict(row['payload']['canonical'])!=FrozenRecord.from_dict(expected_payload)):
            raise ContractError('legacy packet descriptor differs')
        previous=record.content_hash
    if (terminal['kind']!='p0_legacy_extended_terminal' or status not in {'produced','failed'} or value!=expected): raise ContractError('legacy packet terminal differs')
    if status=='failed': return FrozenRecord.from_dict({'schema':'legacy-extended-packet-storage-v1',
        'stage':stage,'error_type':error_type,'storage_verified':True,'operation_validated':False,
        'engineering_verified':False,'scientific_validated':False})
    if set(files)!=set(_PUBLIC): raise ContractError('legacy packet omitted a public output')
    try: public=FrozenRecord((root/'public.json').read_text(encoding='utf-8').strip()).data();receipt=FrozenRecord((root/'receipt.json').read_text(encoding='utf-8').strip()).data()
    except (OSError,UnicodeError,ValueError,ContractError) as exc: raise ContractError('legacy packet public output is unreadable') from exc
    receipt_expected={'identity':task.identity.data(),'task_hash':task.content_hash,'public_projection_written':True,'public_projection_returned':True,'raw_private_payload_returned':False,'access_isolation':'not_verified'}
    if FrozenRecord.from_dict(public)!=FrozenRecord.from_dict(task.data()) or FrozenRecord.from_dict(receipt)!=FrozenRecord.from_dict(receipt_expected):
        raise ContractError('legacy packet public output differs')
    return packet
