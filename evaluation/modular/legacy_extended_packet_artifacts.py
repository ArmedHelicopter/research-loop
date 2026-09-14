"""Sealed public-only witnesses for the legacy extended TRAIN exporter."""
import hashlib
import json
from pathlib import Path
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.ontology import ContractError, canonical

def seal_packet(directory: Path, task: PublicTask, source_sha256: str) -> FrozenRecord:
    files={name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in ('public.json','receipt.json')}
    receipt=FrozenRecord.from_dict({'schema':'legacy-extended-train-packet-v1','identity':task.identity.data(),
        'task_sha256':task.content_hash,'source_sha256':source_sha256,'files':files,
        'raw_private_payload_returned':False,'scope':'train_only'})
    (directory/'packet-seal.json').write_text(receipt.encoded+'\n',encoding='utf-8',newline='\n')
    return verify_packet(directory,task)

def verify_packet(directory: Path, task: PublicTask) -> FrozenRecord:
    try: seal=FrozenRecord((directory/'packet-seal.json').read_text(encoding='utf-8').strip()); public=json.loads((directory/'public.json').read_text(encoding='utf-8')); receipt=json.loads((directory/'receipt.json').read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc: raise ContractError('legacy packet unreadable') from exc
    body=seal.data(); files=body.get('files')
    if (body.get('schema')!='legacy-extended-train-packet-v1' or body.get('scope')!='train_only' or body.get('identity')!=task.identity.data() or body.get('task_sha256')!=task.content_hash or body.get('raw_private_payload_returned') is not False or not isinstance(files,dict) or {n:hashlib.sha256((directory/n).read_bytes()).hexdigest() for n in files}!=files or public!=task.data() or receipt.get('identity')!=task.identity.data()):
        raise ContractError('legacy packet provenance mismatch')
    return seal
