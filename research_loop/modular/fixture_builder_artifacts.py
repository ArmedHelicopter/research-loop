"""Q6.3 fixture outputs and read-only acceptance; no real VAL authorization."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.builder_artifacts import (
    _begin_bound_outputs, _verify_bound_outputs, _match, _read, _snapshot, _FILES, _TERMINAL,
)
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.metaprogram_training import _exclusive
from research_loop.modular.modules.improvement import (
    AcceptanceReceipt, BuilderRegistry, CandidatePackage, FrozenBuilderVersion,
    MetaBuilderCandidate, TrainingManifest,
)
from research_loop.ontology import ContractError

_CATALOGUE = 'fixture-artifacts.jsonl'
_END = 'fixture-terminal.json'
_CLOSURE = 'fixture-closure.json'
_RESULT = 'fixture-result.json'
_LIMIT = ('offline engineering fixtures retain package, receipt, cost and deployment state but do not measure '
          'train gains, validation quality, scientific validity, production host isolation, or cross-process security')
_REJECT_LIMIT = 'invalid builder proposal rejected before meta activation; fixture only'


def _base(task):
    manifest = TrainingManifest.freeze((task.identity,))
    parent = CandidatePackage.create(parent_digest=None, manifest=manifest,
        changes={'memory': {'mode': 'off'}}, search_cost=2)
    fixed = FrozenBuilderVersion.freeze({'entrypoint': 'emit_literal_change_v1',
        'surface': 'memory', 'key': 'mode', 'value': 'fixed-builder'})
    return manifest, parent, fixed


def _inputs(task, controls, variant):
    from research_loop.modular.scenarios_improvement import _controls, improvement_injection
    _controls(task, controls)
    task.identity.require_train()
    injection = improvement_injection('Q6.3', variant)
    manifest, parent, fixed = _base(task)
    return FrozenRecord.from_dict({'schema': 'q63-fixture-artifact-inputs-v1',
        'task': task.data(), 'controls': controls.data(), 'injection': injection.data(),
        'manifest': manifest.record.data(), 'parent': parent.record.data(), 'fixed_builder': fixed.record.data(),
        'search_cost': 2, 'host_source': source_snapshot(Path(__file__).with_name('scenarios_improvement.py'))})


def _spec(kind, payload, parents, *, status='produced', module='M9'):
    return dict(kind=kind, module=module, payload=payload, parents=parents, status=status,
        producer_source=source_snapshot(Path(__file__)), cost={'known': False, 'units': None})


def _files(root):
    if root.is_symlink() or not root.is_dir(): raise ContractError('original fixture directory required')
    ignored = {_CATALOGUE, _CATALOGUE+'.seal.json', _END, _CLOSURE}
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): raise ContractError('fixture output cannot be a symlink')
        if not path.is_file(): continue
        relative=path.relative_to(root).as_posix()
        if relative in ignored: continue
        raw = path.read_bytes()
        result[relative] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    return result


def _db_state(raw):
    db=sqlite3.connect(':memory:')
    try:
        db.deserialize(raw)
        db.execute('PRAGMA query_only=ON')
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if names != {'builder_versions', 'builder_state', 'consumed_meta_receipts'}:
            raise ContractError('fixture registry schema drift')
        return {'versions': [list(row) for row in db.execute('SELECT digest,record FROM builder_versions ORDER BY digest')],
            'active': [list(row) for row in db.execute('SELECT slot,digest FROM builder_state ORDER BY slot')],
            'consumed': [row[0] for row in db.execute('SELECT id FROM consumed_meta_receipts ORDER BY id')]}
    except sqlite3.Error as exc:
        raise ContractError('fixture registry bytes cannot be read') from exc
    finally: db.close()


def _expected_db(fixed, selected=None, receipt=None):
    versions = {fixed.digest: fixed.record.encoded}
    if selected is not None: versions[selected.digest] = selected.record.encoded
    return {'versions': [[key, value] for key,value in sorted(versions.items())],
        'active': [[1, (selected or fixed).digest]], 'consumed': [receipt.receipt_id] if receipt else []}


def _registry_snapshot(root, *, write=False):
    path = root/'builders.sqlite'
    if not path.is_file() or path.is_symlink(): raise ContractError('original fixture registry is missing')
    raw = path.read_bytes(); key = hashlib.sha256(raw).hexdigest()
    blob = root/'fixture-blobs'/key
    if write:
        blob.parent.mkdir(exist_ok=True)
        if not blob.exists():
            with blob.open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    if blob.is_symlink() or not blob.is_file() or blob.read_bytes()!=raw:
        raise ContractError('original fixture registry blob differs')
    return {'file': 'builders.sqlite', 'blob': 'fixture-blobs/'+key,
        'sha256': key, 'bytes': len(raw), 'state': _db_state(raw)}


def _verify_db_snapshot(root, payload, expected):
    if set(payload) != {'file','blob','sha256','bytes','state'} or payload['file']!='builders.sqlite':
        raise ContractError('fixture registry snapshot schema drift')
    key = payload['sha256']
    if (type(key) is not str or len(key)!=64 or any(c not in '0123456789abcdef' for c in key)
            or payload['blob']!='fixture-blobs/'+key):
        raise ContractError('fixture registry blob identity drift')
    path = root/'fixture-blobs'/key
    if not path.is_file() or path.is_symlink(): raise ContractError('fixture registry blob is missing')
    raw=path.read_bytes()
    if (hashlib.sha256(raw).hexdigest()!=key or len(raw)!=payload['bytes']
            or payload['state']!=expected or _db_state(raw)!=expected):
        raise ContractError('fixture registry state differs from actual selection')


def _callback_request(task, injection, fixed, variant):
    kind = 'restricted_builder_execute' if variant=='fixed' else 'meta_builder_candidate'
    body = ({'builder_digest': fixed.digest, 'phase': 'fixed'} if variant=='fixed' else
        {'parent_builder_digest': fixed.digest, 'search_budget': 2, 'allowed_dsl': ['entrypoint','surface','key','value']})
    return FrozenRecord.from_dict({'schema':'m9-public-fixture-callback-v1', 'task':task.data(),
        'kind':kind, 'fixture':injection, 'body':body})


def _proposed(response):
    source = response.data()['builder_dsl'] if set(response.data())=={'builder_dsl'} else None
    return FrozenBuilderVersion.freeze(source)


def _selection(inputs, selected, response, descriptors, variant):
    return _spec('m9_builder_selection', {'schema':'q63-fixture-builder-selection-v1',
        'input_descriptor':descriptors[0].content_hash, 'callback_return_descriptor':descriptors[2].content_hash,
        'registry_descriptor':descriptors[-1].content_hash if variant!='fixed' else None,
        'builder':selected.record.data(), 'builder_digest':selected.digest,
        'response':response.data(), 'response_consumed':variant!='fixed', 'search_cost':2,
        'activation':'applied' if variant!='fixed' else 'not_applied', 'input_digest':inputs.content_hash},
        tuple(dict.fromkeys([descriptors[0].content_hash,descriptors[2].content_hash,descriptors[-1].content_hash])),
        status='produced' if variant!='fixed' else 'not_applied')


def _result(root, variant, task, inputs, response, *, candidate=None, receipt=None, meta=None, rejection=None):
    from research_loop.modular.scenarios_improvement import ImprovementScenarioResult
    manifest,parent,fixed = _base(task)
    detail = {'fixture_only':True, 'train_manifest_digest':manifest.content_hash,
        'baseline_digest':parent.digest, 'search_budget':2, 'injection':inputs.data()['injection']}
    if rejection is not None:
        detail.update(rejected=rejection,active_builder_digest=fixed.digest,candidate_digest=None)
    elif variant=='fixed':
        detail.update(builder_digest=fixed.digest,candidate_digest=candidate.digest,builder_receipt=receipt.record.data())
    else:
        detail.update(meta_package_digest=meta.package.digest,active_builder_digest=meta.next_builder.digest,
            candidate_digest=candidate.digest,builder_receipt=receipt.record.data())
    record = FrozenRecord.from_dict({'experiment_id':'Q6.3','variant':variant,'fixture_only':True,
        'journal_directory':str(root),'callback_count':1,'detail':detail,
        'limitation':_REJECT_LIMIT if rejection is not None else _LIMIT})
    request = _callback_request(task,inputs.data()['injection'],fixed,variant)
    return ImprovementScenarioResult('Q6.3',variant,(request,),(response,),record)


class _Writer:
    def __init__(self, root, task, inputs, variant):
        self.root,self.inputs,self.variant = root,inputs,variant
        self.catalogue = ArtifactCatalogue(root/_CATALOGUE,identity=task.identity,run_id=str(uuid4()),
            experiment_id='Q6.3:'+variant,lock_digest=inputs.content_hash,producer_source=source_snapshot(Path(__file__)))
        self.stage='inputs'; self.records=[]; self.ended=False
        self.append('fixture_inputs',inputs.data(),module='P0')

    def append(self, kind, payload, *, status='produced', module='M9'):
        prior = self.catalogue.records()
        record = self.catalogue.append(**_spec(kind,payload,(prior[-1].content_hash,) if prior else (),status=status,module=module))
        self.records.append(record)
        return record

    def close(self, *, result=None, error=None, rejected=False):
        if self.ended: raise ContractError('fixture was already closed')
        if result is not None:
            _exclusive(self.root/_RESULT,result.record)
            self.append('fixture_result',_snapshot(self.root,_RESULT),status='rejected' if rejected else 'produced',module='P0')
        status='failed' if error else 'rejected' if rejected else 'succeeded'
        terminal=FrozenRecord.from_dict({'schema':'q63-fixture-terminal-v1','status':status,'stage':self.stage,
            'error_type':type(error).__name__ if error else None,'error':str(error) if error else None,
            'result_digest':result.record.content_hash if result else None,'files':_files(self.root),
            'scientific_validated':False})
        _exclusive(self.root/_END,terminal)
        self.append('fixture_terminal',_snapshot(self.root,_END),status='failed' if error else 'rejected' if rejected else 'produced',module='P0')
        seal=self.catalogue.seal()
        _exclusive(self.root/_CLOSURE,FrozenRecord.from_dict({'schema':'q63-fixture-closure-v1',
            'catalogue_seal':seal.data(),'terminal':_snapshot(self.root,_END)}))
        self.ended=True


def run_q63_fixture(*, task, frozen_controls, sidecar, variant, callback=None):
    from research_loop.modular.scenarios_improvement import _authority, _signed_validation
    root=Path(sidecar); inputs=_inputs(task,frozen_controls,variant)
    if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
        raise ContractError('fixture build requires its newly created empty directory')
    manifest,parent,fixed=_base(task); writer=_Writer(root,task,inputs,variant)
    try:
        writer.stage='callback'
        request=_callback_request(task,inputs.data()['injection'],fixed,variant)
        callback_status='not_applied' if variant=='fixed' else 'produced'
        writer.append('fixture_callback_request',request.data(),status=callback_status)
        response=callback(request) if callback else FrozenRecord.from_dict({'kind':request.data()['kind'],'result':'fixture-callback-output'})
        writer.append('fixture_callback_return',{'record':response.data() if type(response) is FrozenRecord else None,
            'returned_type':type(response).__name__,'raw_content_available':type(response) is FrozenRecord},
            status=callback_status if type(response) is FrozenRecord else 'rejected')
        if type(response) is not FrozenRecord: raise ContractError('improvement callback must return FrozenRecord')
        writer.stage='selection'; selected=fixed; meta=None
        if variant!='fixed':
            try: selected=_proposed(response)
            except (ContractError,KeyError,TypeError) as exc:
                result=_result(root,variant,task,inputs,response,rejection=str(exc))
                writer.close(result=result,rejected=True)
                return result
            meta=MetaBuilderCandidate.propose(parent_package=parent,parent_builder=fixed,next_builder=selected,
                manifest=manifest,search_cost=2)
            writer.append('fixture_meta_candidate',{'package':meta.package.record.data(),'parent_builder_digest':meta.parent_builder_digest,
                'next_builder':selected.record.data()})
            authority=_authority(lambda:meta.package,lambda:parent)
            validation=_signed_validation()
            writer.stage='fixture_acceptance'
            writer.append('fixture_acceptance_request',{'record':validation.record.data(),'signature':validation.signature,
                'candidate_digest':meta.package.digest,'parent_digest':parent.digest,'fixture_only':True})
            acceptance=authority.validate(meta.package,parent.digest,validation)
            writer.append('fixture_acceptance_return',{'record':acceptance.record.data(),'signature':acceptance.signature,'fixture_only':True})
            writer.stage='registry_initialize'
            registry=BuilderRegistry(root/'builders.sqlite',authority,fixed)
            try:
                writer.append('fixture_registry_initialized',_registry_snapshot(root,write=True))
                writer.stage='registry_activate'
                writer.append('fixture_registry_request',{'meta_package_digest':meta.package.digest,'receipt_id':acceptance.receipt_id,
                    'parent_builder_digest':fixed.digest,'next_builder_digest':selected.digest})
                registry.activate_meta(meta,acceptance)
                actual=registry.active()
                if actual!=selected: raise ContractError('fixture registry did not select the accepted builder')
                writer.append('fixture_registry_active',_registry_snapshot(root,write=True))
            finally: registry.close()
        writer.stage='builder'
        bridge=_begin_bound_outputs(writer.catalogue,root=root,builder=selected,parent=parent,manifest=manifest,
            enabled=variant!='fixed',search_cost=2,strict_projection=False,
            selection_spec=_selection(inputs,selected,response,writer.records,variant))
        candidate,receipt=bridge.execute()
        writer.stage='complete'
        result=_result(root,variant,task,inputs,response,candidate=candidate,receipt=receipt,meta=meta)
        writer.close(result=result)
        return result
    except Exception as exc:
        if not writer.ended:
            try: writer.close(error=exc)
            except Exception as journal_error: exc.add_note('fixture artifact closure failure: '+type(journal_error).__name__)
        raise


def _open_catalogue(root, task, inputs, variant):
    path=root/_CATALOGUE
    if root.is_symlink() or path.is_symlink() or not path.is_file() or not path.with_name(path.name+'.seal.json').is_file():
        raise ContractError('original sealed fixture catalogue is missing')
    try:
        first=FrozenRecord(path.read_text(encoding='utf-8').splitlines()[0]).data()['descriptor']
        binding=first['binding']
        catalogue=ArtifactCatalogue(path,identity=task.identity,**binding,producer_source=first['producer_source'])
    except (IndexError,KeyError,TypeError) as exc:
        raise ContractError('fixture catalogue has no original run binding') from exc
    if binding['experiment_id']!='Q6.3:'+variant or binding['lock_digest']!=inputs.content_hash or not binding['run_id']:
        raise ContractError('fixture run binding differs from original inputs')
    return catalogue


def verify_q63_fixture(result, *, task, frozen_controls, sidecar, variant):
    """Verify successful/rejected original results; never create files or activate a registry."""
    from research_loop.modular.scenarios_improvement import ImprovementScenarioResult, _authority, _signed_validation
    from research_loop.modular.modules.improvement import BuilderRunReceipt
    if type(result) is not ImprovementScenarioResult: raise ContractError('original fixture result required')
    root=Path(sidecar); inputs=_inputs(task,frozen_controls,variant); manifest,parent,fixed=_base(task)
    catalogue=_open_catalogue(root,task,inputs,variant)
    records=list(catalogue.records()); cursor=0; prefix=[]
    def payload(kind):
        if cursor>=len(records) or records[cursor].data()['kind']!=kind:
            raise ContractError('fixture original output is missing or out of order')
        value=records[cursor].data()['payload']['canonical']
        if type(value) is not dict: raise ContractError('fixture original output has no canonical body')
        return value
    def take(kind,payload,*,status='produced',module='M9'):
        nonlocal cursor
        if cursor>=len(records): raise ContractError('fixture original output is missing')
        row=records[cursor]
        _match(row,_spec(kind,payload,(records[cursor-1].content_hash,) if cursor else (),status=status,module=module))
        prefix.append(row);cursor+=1
        return row
    take('fixture_inputs',inputs.data(),module='P0')
    request=_callback_request(task,inputs.data()['injection'],fixed,variant)
    callback_status='not_applied' if variant=='fixed' else 'produced'
    take('fixture_callback_request',request.data(),status=callback_status)
    if result.callback_payloads!=(request,) or len(result.callback_outputs)!=1 or type(result.callback_outputs[0]) is not FrozenRecord:
        raise ContractError('fixture result differs from original callback invocation')
    response=result.callback_outputs[0]
    take('fixture_callback_return',{'record':response.data(),'returned_type':'FrozenRecord','raw_content_available':True},status=callback_status)
    selected=fixed;meta=None;rejection=None;blobs=set()
    if variant!='fixed':
        try: selected=_proposed(response)
        except (ContractError,KeyError,TypeError) as exc: rejection=str(exc)
        if rejection is None:
            meta=MetaBuilderCandidate.propose(parent_package=parent,parent_builder=fixed,next_builder=selected,manifest=manifest,search_cost=2)
            take('fixture_meta_candidate',{'package':meta.package.record.data(),'parent_builder_digest':meta.parent_builder_digest,
                'next_builder':selected.record.data()})
            validation=_signed_validation()
            take('fixture_acceptance_request',{'record':validation.record.data(),'signature':validation.signature,
                'candidate_digest':meta.package.digest,'parent_digest':parent.digest,'fixture_only':True})
            raw=payload('fixture_acceptance_return')
            if set(raw)!={'record','signature','fixture_only'} or type(raw['record']) is not dict or type(raw['signature']) is not str:
                raise ContractError('fixture acceptance return schema drift')
            acceptance=AcceptanceReceipt(FrozenRecord.from_dict(raw['record']),raw['signature'])
            _authority(lambda:meta.package,lambda:parent).verify(acceptance)
            expected={'validator_id':'fixture-independent-validation','candidate_digest':meta.package.digest,
                'expected_active_digest':parent.digest,'trial_digest':'a'*64,'domain':'validation','offline':False,'decision':'approved'}
            if acceptance.record.data()!=expected: raise ContractError('fixture acceptance does not bind the actual meta candidate')
            take('fixture_acceptance_return',{'record':expected,'signature':acceptance.signature,'fixture_only':True})
            raw=payload('fixture_registry_initialized')
            _verify_db_snapshot(root,raw,_expected_db(fixed));blobs.add(raw['blob'])
            take('fixture_registry_initialized',raw)
            take('fixture_registry_request',{'meta_package_digest':meta.package.digest,'receipt_id':acceptance.receipt_id,
                'parent_builder_digest':fixed.digest,'next_builder_digest':selected.digest})
            raw=payload('fixture_registry_active')
            _verify_db_snapshot(root,raw,_expected_db(fixed,selected,acceptance));blobs.add(raw['blob'])
            if _registry_snapshot(root)!=raw: raise ContractError('final fixture registry differs from retained activation')
            take('fixture_registry_active',raw)
    candidate=receipt=None
    if rejection is None:
        payload('m9_builder_selection')
        selection=records[cursor]
        _match(selection,_selection(inputs,selected,response,prefix,variant))
        report=_verify_bound_outputs(catalogue,root=root,builder=selected,parent=parent,manifest=manifest,
            enabled=variant!='fixed',selection=selection,search_cost=2,strict_projection=False)
        if report.data()['status']!='succeeded': raise ContractError('successful fixture requires successful original builder')
        block=records[cursor:cursor+7]
        if len(block)!=7 or any(not r.data()['kind'].startswith('m9_') for r in block):
            raise ContractError('fixture builder outputs are not one contiguous transaction')
        cursor+=7
        candidate=CandidatePackage(_read(root,'candidate.json'));receipt=BuilderRunReceipt(_read(root,'builder-receipt.json'))
    expected=_result(root,variant,task,inputs,response,candidate=candidate,receipt=receipt,meta=meta,rejection=rejection)
    if result!=expected or _read(root,_RESULT)!=result.record: raise ContractError('fixture result differs from original output replay')
    take('fixture_result',_snapshot(root,_RESULT),status='rejected' if rejection is not None else 'produced',module='P0')
    terminal=_read(root,_END)
    expected_files={_RESULT,*blobs}
    if rejection is None: expected_files.update((*_FILES,_TERMINAL))
    if meta is not None: expected_files.add('builders.sqlite')
    files=_files(root)
    if set(files)!=expected_files: raise ContractError('fixture has missing or unexpected original files')
    expected_terminal={'schema':'q63-fixture-terminal-v1','status':'rejected' if rejection is not None else 'succeeded',
        'stage':'selection' if rejection is not None else 'complete','error_type':None,'error':None,
        'result_digest':result.record.content_hash,'files':files,'scientific_validated':False}
    if terminal.data()!=expected_terminal: raise ContractError('fixture terminal differs from original result and output files')
    take('fixture_terminal',_snapshot(root,_END),status='rejected' if rejection is not None else 'produced',module='P0')
    if cursor!=len(records): raise ContractError('fixture has unconsumed artifact records')
    seal=_read(root,_CATALOGUE+'.seal.json');catalogue.verify(seal)
    if _read(root,_CLOSURE).data()!={'schema':'q63-fixture-closure-v1','catalogue_seal':seal.data(),'terminal':_snapshot(root,_END)}:
        raise ContractError('fixture closure does not bind the original sealed outputs')
    return FrozenRecord.from_dict({'schema':'q63-fixture-artifacts-verified-v1','status':expected_terminal['status'],
        'descriptor_count':len(records),'scientific_validated':False,'scientific_effect':'not_measured'})


def inspect_q63_fixture_failure(*, task, frozen_controls, sidecar, variant):
    """Read a failed attempt's retained storage; this is not stage acceptance."""
    root=Path(sidecar);inputs=_inputs(task,frozen_controls,variant)
    catalogue=_open_catalogue(root,task,inputs,variant);records=list(catalogue.records())
    if len(records)<2: raise ContractError('failed fixture has no retained input and terminal')
    _match(records[0],_spec('fixture_inputs',inputs.data(),(),module='P0'))
    terminal=_read(root,_END).data()
    if (set(terminal)!={'schema','status','stage','error_type','error','result_digest','files','scientific_validated'}
            or terminal['schema']!='q63-fixture-terminal-v1' or terminal['status']!='failed'
            or terminal['stage'] not in {'inputs','callback','selection','fixture_acceptance',
                'registry_initialize','registry_activate','builder','complete'}
            or type(terminal['error_type']) is not str or not terminal['error_type']
            or type(terminal['error']) is not str or terminal['result_digest'] is not None
            or terminal['scientific_validated'] is not False or terminal['files']!=_files(root)):
        raise ContractError('failed fixture terminal does not bind retained storage')
    _match(records[-1],_spec('fixture_terminal',_snapshot(root,_END),(records[-2].content_hash,),status='failed',module='P0'))
    seal=_read(root,_CATALOGUE+'.seal.json');catalogue.verify(seal)
    if _read(root,_CLOSURE).data()!={'schema':'q63-fixture-closure-v1','catalogue_seal':seal.data(),'terminal':_snapshot(root,_END)}:
        raise ContractError('failed fixture closure drift')
    return FrozenRecord.from_dict({'schema':'q63-fixture-failure-storage-v1','status':'failed',
        'stage':terminal['stage'],'error_type':terminal['error_type'],'error':terminal['error'],
        'files':terminal['files'],'descriptor_count':len(records),'storage_integrity_verified':True,
        'stage_semantics_verified':False,'scientific_validated':False,'acceptance_eligible':False})
