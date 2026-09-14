"""P0 witnesses for actual public TRAIN packet writes and failed partial writes.

No private source or partition index is opened here. The owning exporter first
checks allocation and reserves exposure; this adapter records only that public
task, its selected request and the resulting public files.
"""
from pathlib import Path
import hashlib
from uuid import uuid4

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.ontology import ContractError

R = FrozenRecord.from_dict
_CAT = 'artifacts.jsonl'
_SEAL = _CAT+'.seal.json'
_FILES = ('public.json', 'data.csv', 'receipt.json')


def _path(path):
    from evaluation.modular.prospective_train_exporter import _concrete
    return _concrete(path)


def _file(path):
    path = _path(path); raw = path.read_bytes()
    return {'file':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def _record_file(path):
    raw = _path(path).read_bytes()
    try: record = FrozenRecord(raw.decode('utf-8').removesuffix('\n'))
    except (UnicodeError, ContractError) as exc:
        raise ContractError('public export file is not canonical JSON') from exc
    if raw != (record.encoded+'\n').encode('utf-8'):
        raise ContractError('public export file bytes differ from canonical JSON')
    return record


def _files(root):
    root = _path(root)
    paths = list(root.iterdir())
    if any(not p.is_file() or p.name not in {*_FILES,_CAT,_SEAL} for p in paths):
        raise ContractError('unregistered public export output')
    return {name:_file(root/name) for name in _FILES if (root/name).exists()}


def _public_files(root, task, metadata, primary):
    task.identity.require_train()
    expected = {'task':task.data(),'receipt':metadata} if primary else task.data()
    if _record_file(root/'public.json').data() != expected or _record_file(root/'receipt.json').data() != metadata:
        raise ContractError('original public task or receipt differs')
    files = _files(root)
    if set(files) != ({'public.json','data.csv','receipt.json'} if primary else {'public.json','receipt.json'}):
        raise ContractError('public export file inventory differs')
    if primary:
        if (metadata.get('identity') != task.identity.data() or metadata.get('packet_hash') != task.content_hash
                or metadata.get('csv_sha256') != files['data.csv']['sha256']
                or metadata.get('csv_byte_count') != files['data.csv']['bytes']):
            raise ContractError('original public CSV or task binding differs')
    elif (metadata.get('task_sha256') != task.content_hash
            or metadata.get('public_file_sha256') != files['public.json']['sha256']
            or metadata.get('identity_sha256') != R(task.identity.data()).content_hash):
        raise ContractError('extended public task binding differs')
    return files


def _method_source(method):
    return {'callable':method.__qualname__, 'source':source_snapshot(Path(method.__code__.co_filename))}


class TrainPacketArtifacts:
    def __init__(self, root, *, exporter, item, task, attempt, request_digest, source_digests):
        if type(task) is not PublicTask:
            raise ContractError('P0 packet requires its exact public task')
        task.identity.require_train()
        self.root, self.task = _path(root), task
        self.primary = task.identity.benchmark in {'blade','discoverybench'}
        self.binding = R({'schema':'train-packet-artifact-binding-v1','task_digest':task.content_hash,
            'identity':task.identity.data(),'item':item.data(),'attempt':attempt,'request_digest':request_digest,
            'split_digest':exporter.expected_split_digest,'audit_digest':exporter.expected_audit_digest,
            'source_receipt_digest':source_digests[item.source],
            'exposure_reservation':{'sequence':exporter._sequence,'head':exporter._previous},
            'public_format':'primary' if self.primary else 'extended',
            'producer_methods':{'export':_method_source(exporter.export),
                'projection':_method_source(exporter._prepare_task),'packet_writer':_method_source(exporter._write_public_packet)},
            'validation_index_included':False,'scientific_validated':False})
        if self.root.exists() and any(self.root.iterdir()):
            raise ContractError('P0 public packet directory already used')
        self.catalogue = ArtifactCatalogue(self.root/_CAT, identity=task.identity,run_id=uuid4().hex,
            experiment_id='P0:train-export',lock_digest=self.binding.content_hash,
            producer_source=source_snapshot(Path(__file__)))
        self.last = self.catalogue.append(kind='p0_train_packet_binding',module='P0',payload=self.binding)
        self.seen = {}; self.terminal = None

    def _observe(self):
        files = _files(self.root)
        for name, snapshot in files.items():
            if name in self.seen:
                if self.seen[name] != snapshot: raise ContractError('registered public packet file changed')
                continue
            self.last = self.catalogue.append(kind='p0_public_export_file',module='P0',payload=snapshot,
                parents=(self.last.content_hash,))
            self.seen[name] = snapshot
        return files

    def _finish(self, status, metadata, error_code):
        files = self._observe()
        payload = R({'schema':'train-packet-artifact-terminal-v1','status':status,
            'files':files,'metadata':metadata,'error_code':error_code,
            'model_calls':0,'network_calls':0,'call_scope':'local_packet_writer',
            'total_resource_cost_known':False,'scientific_validated':False})
        self.terminal = self.catalogue.append(kind='p0_train_packet_terminal',module='P0',payload=payload,
            parents=(self.last.content_hash,),status=status)
        seal = self.catalogue.seal(); raw = self.catalogue.path.read_bytes()
        return {'token':self.binding.data()['item']['token'],'identity':self.task.identity.data(),
            'binding':self.binding.data(),'journal_sha256':hashlib.sha256(raw).hexdigest(),'journal_bytes':len(raw),
            'seal':seal.data(),'seal_digest':seal.content_hash}

    def finish(self, metadata):
        _public_files(self.root,self.task,metadata,self.primary)
        return self._finish('produced',metadata,None)

    def fail(self, error):
        if self.terminal is not None: return
        from evaluation.modular.fresh_airs_hf_custodian import safe_error
        # The original exporter owns the redacted batch failure. Never copy an
        # exception message containing a private path or record into public P0.
        self._finish('failed',None,safe_error(error))


def verify_train_export_artifacts(root, receipt, tasks):
    """Verify each packet against the original batch anchor, without private reads.

    The owner must authenticate the export receipt against its completion journal
    or pinned bytes. This function cannot authenticate an arbitrary caller value.
    """
    if type(receipt) is not FrozenRecord or type(tasks) is not tuple or not tasks or any(type(t) is not PublicTask for t in tasks):
        raise ContractError('P0 export reader requires exact tasks and frozen receipt')
    for task in tasks: task.identity.require_train()
    body = receipt.data()
    anchors = body.get('artifact_catalogues'); metadata = body.get('packets')
    if (body.get('schema') != 'prospective-train-export-receipt-v2' or type(anchors) is not list
            or type(metadata) is not list or len(anchors) != len(metadata) or len(tasks) != len(anchors)):
        raise ContractError('P0 export lacks its exact packet anchors')
    # Complete domain/token checks precede any path resolution or public reads.
    tokens = []
    for anchor, task in zip(anchors,tasks,strict=True):
        if (type(anchor) is not dict or set(anchor) != {'token','identity','binding','journal_sha256','journal_bytes','seal','seal_digest'}
                or anchor['identity'] != task.identity.data()):
            raise ContractError('P0 export anchor subject differs')
        token = anchor['token']
        if not isinstance(token,str) or len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
            raise ContractError('P0 export token is invalid')
        tokens.append(token)
    if len(set(tokens)) != len(tokens): raise ContractError('P0 export tokens repeat')
    root = _path(root); summaries = []; observed = {}
    for task, anchor, packet in zip(tasks,anchors,metadata,strict=True):
        directory = root/anchor['token']; binding = R(anchor['binding']); b = binding.data()
        if (b.get('schema') != 'train-packet-artifact-binding-v1' or b.get('identity') != task.identity.data()
                or b.get('task_digest') != task.content_hash or b.get('split_digest') != body['split_sha256']
                or task.identity.split_id != body['split_sha256'] or b.get('audit_digest') != body['audit_sha256']
                or b.get('request_digest') != body['request_sha256'] or b.get('item',{}).get('token') != anchor['token']
                or b.get('item',{}).get('source') != task.identity.benchmark
                or b.get('item',{}).get('group_sha256') != task.identity.group_id
                or b.get('source_receipt_digest') != body['source_receipt_digests'].get(task.identity.benchmark)
                or b.get('validation_index_included') is not False or b.get('scientific_validated') is not False):
            raise ContractError('P0 public packet provenance differs from the batch')
        path = _path(directory/_CAT); raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != anchor['journal_sha256'] or len(raw) != anchor['journal_bytes']:
            raise ContractError('P0 original catalogue bytes differ')
        try: first = FrozenRecord(raw.splitlines()[0].decode('utf-8')).data()['descriptor']
        except (IndexError, KeyError, UnicodeError) as exc:
            raise ContractError('P0 packet catalogue is missing its original binding') from exc
        catalogue = ArtifactCatalogue(path,identity=task.identity,**first['binding'])
        methods = b.get('producer_methods')
        if not isinstance(methods,dict) or set(methods) != {'export','projection','packet_writer'}:
            raise ContractError('P0 packet producer methods are missing')
        for method in methods.values():
            if (not isinstance(method,dict) or set(method) != {'callable','source'}
                    or not isinstance(method['callable'],str) or not method['callable']):
                raise ContractError('P0 packet producer method differs')
            catalogue._verify_source(method['source'])
        if not _path(directory/_SEAL).is_file(): raise ContractError('P0 packet seal is missing')
        seal = R(anchor['seal']); catalogue.verify(seal)
        if seal.content_hash != anchor['seal_digest'] or catalogue.binding['lock_digest'] != binding.content_hash:
            raise ContractError('P0 packet seal or lock differs')
        records = catalogue.records(); primary = task.identity.benchmark in {'blade','discoverybench'}
        if b.get('public_format') != ('primary' if primary else 'extended'):
            raise ContractError('P0 public packet format differs')
        files = _public_files(directory,task,packet,primary)
        if packet.get('export_token' if primary else 'token') != anchor['token']:
            raise ContractError('P0 packet receipt token differs')
        if (len(records) != len(files)+2 or records[0].data()['kind'] != 'p0_train_packet_binding'
                or records[0].data()['payload']['canonical'] != b):
            raise ContractError('P0 catalogue does not cover its original packet')
        previous = records[0]
        for record, snapshot in zip(records[1:-1],files.values(),strict=True):
            row = record.data()
            if (row['kind'] != 'p0_public_export_file' or row['payload']['canonical'] != snapshot
                    or row['parents'] != [previous.content_hash] or row['module'] != 'P0' or row['status'] != 'produced'):
                raise ContractError('P0 file descriptor differs from its original output')
            previous = record
        terminal = records[-1].data()
        expected = {'schema':'train-packet-artifact-terminal-v1','status':'produced','files':files,
            'metadata':packet,'error_code':None,'model_calls':0,'network_calls':0,
            'call_scope':'local_packet_writer','total_resource_cost_known':False,'scientific_validated':False}
        if (terminal['kind'] != 'p0_train_packet_terminal' or terminal['payload']['canonical'] != expected
                or terminal['parents'] != [previous.content_hash] or terminal['status'] != 'produced'
                or any(r.data()['module'] != 'P0' or r.data()['optimizer_visible']
                    or r.data()['cost'] != {'known':False,'units':None} for r in records)):
            raise ContractError('P0 public packet terminal differs')
        summaries.append({'token':anchor['token'],'seal_digest':seal.content_hash,'files':len(files)})
        observed[anchor['token']+'/'+_CAT] = anchor['journal_sha256']
        observed[anchor['token']+'/'+_SEAL] = hashlib.sha256((seal.encoded+'\n').encode('utf-8')).hexdigest()
        observed.update({anchor['token']+'/'+name:value['sha256'] for name,value in files.items()})
    return R({'schema':'train-export-artifacts-verified-v1','packets':summaries,
        'observed_public_files':observed,
        'private_sources_read':False,'scientific_validated':False,'validation_access_authorized':False})
