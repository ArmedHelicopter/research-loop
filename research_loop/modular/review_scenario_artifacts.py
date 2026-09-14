"""Durable, fixture-only Q4 scenario audit records."""
from __future__ import annotations
import hashlib, os
from pathlib import Path
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.ontology import ContractError

_FILES=("review-inputs.json","review-callbacks.json","review-result.json","review-terminal.json")
def _write(path, record):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as f:f.write(record.encoded+'\n');f.flush();os.fsync(f.fileno())
def _read(path):
    if path.is_symlink() or not path.is_file():raise ContractError('original review artifact is missing')
    return FrozenRecord(path.read_text(encoding='utf-8').strip())
def _snap(root, names=_FILES):
    out={}
    for name in names:
        path=root/name
        if path.is_symlink() or not path.is_file():raise ContractError('review artifact missing')
        raw=path.read_bytes();out[name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    return out

def write_review_artifacts(root, *, task, controls, result):
    root=Path(root)
    if root.is_symlink() or any(p.is_symlink() for p in root.parents) or root.exists() and any(root.iterdir()):raise ContractError('review artifact root must be new and unlinked')
    root.mkdir(parents=True,exist_ok=False)
    source=source_snapshot(Path(__file__))
    inputs=FrozenRecord.from_dict({'schema':'q4-review-artifact-inputs-v1','fixture_only':True,'task':task.data(),'controls':controls.data(),'experiment_id':result.experiment_id,'variant':result.variant,'source':source})
    _write(root/_FILES[0],inputs)
    callbacks=FrozenRecord.from_dict({'schema':'q4-review-artifact-callbacks-v1','payloads':[x.data() for x in result.callback_payloads],'responses':[x.data() for x in result.callback_responses],'trace':result.mechanism_trace.data(),'fixture_only':True})
    _write(root/_FILES[1],callbacks)
    _write(root/_FILES[2],result.record)
    terminal=FrozenRecord.from_dict({'schema':'q4-review-artifact-terminal-v1','status':'succeeded','files':_snap(root,_FILES[:3]),'fixture_only':True,'scientific_validated':False})
    _write(root/_FILES[3],terminal)
    return FrozenRecord.from_dict({'schema':'q4-review-artifacts-written-v1','root':str(root),'files':_snap(root),'fixture_only':True})

def verify_review_artifacts(root, *, task, controls, result):
    root=Path(root);inputs=_read(root/_FILES[0]).data();callbacks=_read(root/_FILES[1]).data()
    if inputs.get('task')!=task.data() or inputs.get('controls')!=controls.data() or inputs.get('experiment_id')!=result.experiment_id or inputs.get('variant')!=result.variant:raise ContractError('review artifact inputs differ')
    if callbacks!={'schema':'q4-review-artifact-callbacks-v1','payloads':[x.data() for x in result.callback_payloads],'responses':[x.data() for x in result.callback_responses],'trace':result.mechanism_trace.data(),'fixture_only':True}:raise ContractError('review callback audit differs')
    if _read(root/_FILES[2])!=result.record:raise ContractError('review result differs')
    terminal=_read(root/_FILES[3]).data()
    if terminal!={'schema':'q4-review-artifact-terminal-v1','status':'succeeded','files':_snap(root,_FILES[:3]),'fixture_only':True,'scientific_validated':False}:raise ContractError('review terminal differs')
    return FrozenRecord.from_dict({'schema':'q4-review-artifacts-verified-v1','status':'succeeded','scientific_validated':False})
