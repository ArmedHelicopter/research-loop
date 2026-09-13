"""Independent public fixtures for 88 causal cells; all observations run Docker."""
import base64
import csv
import io
import json
import os
from copy import deepcopy
from hashlib import sha256

import pytest

from research_loop.modular import panel_plan, panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionReceipt
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import scenario as base_scenario
from research_loop.modular.exploration_extended_panel_drivers import (
    LIMITS, VARIANTS, freeze_extended_exploration_bundle, extended_exploration_injection, install_drivers,
    freeze_ratio_selection, select_training_ratio,
    _append_prior_observation,
)
from research_loop.modular.modules.admission import AuditItem, ScientificState
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import AuditAuthority, AuditVerifier
from research_loop.ontology import ContractError

IMAGE = 'research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'
CODE = "import csv,json\nwith open('/input/data_csv') as f: rows=list(csv.DictReader(f))\nfield='x'\nxs=[float(r[field]) for r in rows]\nprint(json.dumps({'mean':sum(xs)/len(xs),'control':sum(x-x for x in xs),'field':field}))\n"
BUDGET = {key: {'model_calls': values[0], 'execution_opportunities': values[1], 'verification_calls': values[2]} for key,values in LIMITS.items()}


def _task(name):
    identity = DataIdentity(name, 'extended-public', name + ':extended', 'synthetic-v2', '8' * 64, 'train')
    if name == 'blade':
        return BladeAdapter().prepare(identity, {'task_id': identity.task_id, 'dataset_id': 'public', 'research_question': 'Test the declared construct using public measurements.', 'data_schema': [{'name': 'x', 'dtype': 'float'}]})
    return DiscoveryBenchAdapter().prepare(identity, {'task_id': identity.task_id, 'question': 'Test the declared construct using public measurements.', 'source_kind': 'synthetic', 'dataset': [{'name': 'x', 'columns': [{'name': 'x'}]}]})


class Authority:
    """Verifier recalculates actual bytes against two pre-frozen source documents.

    Its facts never inspect the arm or variant. Documents include concrete
    calibration, construct, prior publication and utility thresholds; the
    receipt signature is applied only after those checks succeed.
    """
    def __init__(self):
        self.keys = {'a': b'a' * 32, 'b': b'b' * 32}
        self.documents = {}; self.calls = []; self.fault = None

    def verify_preflight(self, subject): return self._call(subject, False)
    def verify_observation(self, subject): return self._call(subject, True)

    def _call(self, subject, observed):
        body = subject.data(); self.calls.append(body)
        if self.fault in ('partial_known', 'partial_unknown'):
            error = OSError('synthetic transport failure')
            cost = {'unit': 'verifier_units', 'units': 2 if self.fault == 'partial_known' else None}
            error.partial_response = FrozenRecord.from_dict({'schema': 'partial-v1', 'subject_digest': subject.content_hash, 'cost': cost})
            error.cost = cost
            raise error
        job = body['diagnostic']; contract = body['authority_contract']; docs = []; proofs = []
        for declared in contract['authorities']:
            doc = self.documents[(contract['contract_id'], declared['authority_id'], job['diagnostic_id'])]
            assert doc['task_digest'] == body['task_digest'] and doc['identity'] == body['identity']
            assert doc['job'] == job
            docs.append(doc)
            proofs.append({**declared, 'subject_digest': subject.content_hash, 'contract_id': contract['contract_id'],
                'observation_digest': FrozenRecord.from_dict(doc).content_hash, 'signature_verified': True})
        d = docs[0]
        facts = {'safe': True, 'authorized': d['hard'] != 'authorization', 'resources_available': d['hard'] != 'resource',
            'diagnostic_inputs_available': True, 'scientific_data_status': 'passed' if d['data_known'] else 'unknown', 'block_status': 'unknown'}
        row = {'schema': 'exploration-preflight-verified-v1', 'subject_digest': subject.content_hash,
            'observations': proofs, 'facts': facts, 'cost': {'unit': 'verifier_units', 'units': None if self.fault == 'unknown_cost' else 1}}
        if observed:
            material = body['trusted_execution_material']; receipt = ExecutionReceipt.parse(material['execution_receipt'])
            assert receipt.content_hash == body['execution_digest']
            program = base64.b64decode(material['program_bytes_b64'], validate=True)
            assert sha256(program).hexdigest() == job['program_sha256'] == receipt.artifact.sha256
            assert len(program) == receipt.artifact.byte_count
            supplied = material['public_input_bytes']['data_csv']; content = base64.b64decode(supplied['bytes_b64'], validate=True)
            expected = job['inputs']['data_csv']
            assert sha256(content).hexdigest() == expected['sha256'] == supplied['sha256']
            assert len(content) == expected['byte_count'] == supplied['byte_count']
            assert receipt.record.data()['input_artifacts']['data_csv'] == {'artifact_id': 'data_csv', **expected}
            assert receipt.record.data()['stdout'] == body['execution_observation']['stdout']
            table = list(csv.DictReader(io.StringIO(content.decode())))
            output = json.loads(receipt.record.data()['stdout']) if receipt.status == 'succeeded' else None
            # Two frozen literal source observations plus a fresh calculation
            # using the actual supplied CSV must agree, not merely exit zero.
            matches = output is not None and all(output['mean'] == doc['expected_mean'] == sum(float(r[doc['measured_field']]) / len(table) for r in table)
                and output['field'] == doc['measured_field'] for doc in docs)
            controlled = matches and all(output['control'] == doc['control_target'] for doc in docs)
            semantic = controlled and all(output['field'] == doc['construct_field'] for doc in docs)
            known = all(doc['data_known'] for doc in docs)
            qualified = semantic and known
            validity = 'valid' if qualified else 'invalid' if matches and not semantic else 'unknown'
            outcome = 'positive' if output is not None and output['mean'] > 0 else 'negative'
            state = ScientificState(validity, ('supported' if outcome == 'positive' else 'refuted') if qualified else 'undetermined', d['novelty'], d['investment'])
            role = body['job_role']
            prior_match = all(doc['publication_observation'] is not None and output is not None and
                doc['publication_observation'] == {'field': output['field'], 'mean': output['mean']} for doc in docs)
            row.update(schema='exploration-observation-verified-v1', facts={
                'block_status': 'cleared' if qualified else 'unknown', 'resource_request_verified': job['requirements'] == {'execution_units': 1, 'token_units': 1},
                'diagnostic_answer': 'repair_supported' if qualified else 'inconclusive',
                'scientific_status': 'qualified_' + outcome if qualified else 'data_unknown' if not known else 'measurement_repair'},
                facets={'mechanical_status': 'passed' if matches else 'failed', 'semantic_status': 'passed' if semantic else 'failed' if matches else 'unknown',
                    'diagnostic_value': ('effective' if controlled and not d['already_known'] else 'waste' if controlled else 'unknown') if role == 'diagnostic' else 'not_applicable',
                    'main_progress': ('completed' if qualified and output['mean'] >= d['main_threshold'] else 'incomplete' if known else 'unknown') if role == 'main' else 'not_applicable',
                    'prior_art_status': 'matched' if prior_match else 'not_matched',
                    'old_instrument_status': 'valid' if controlled else 'invalid' if matches else 'unknown'},
                audits=[AuditAuthority(aid, key).issue(identity=DataIdentity.parse(body['identity']), objective_digest=body['objective_digest'],
                    execution_digest=body['execution_digest'], state=state, outcome=outcome,
                    audit=[AuditItem('measurement', True, qualified)]).data() for aid,key in self.keys.items()])
            if self.fault == 'false_semantic': row['facets']['semantic_status'] = 'failed'
        if self.fault == 'subject': row['subject_digest'] = '0' * 64
        return FrozenRecord.from_dict(row)


def _item(task, path, authority, *, count=1, bad=False, repaired=True, construct='x', measured='x', known=True,
          novelty='unknown', investment='explore', prior=False, hard='none', ratio=False):
    content = path.read_bytes(); inputs = {'data_csv': {'sha256': sha256(content).hexdigest(), 'byte_count': len(content)}}
    jobs = []; values = list(csv.DictReader(io.StringIO(content.decode())))
    for index in range(count):
        code = CODE.replace('sum(x-x for x in xs)', '1.0') if bad and (index == 0 or not repaired) else CODE
        code = code.replace("field='x'", "field='" + measured + "'")
        job = {'diagnostic_id': 'job_' + str(index), 'program': code,
            'program_sha256': sha256(code.replace('\n', os.linesep).encode()).hexdigest(), 'image': IMAGE, 'inputs': inputs,
            'requirements': {'execution_units': 1, 'token_units': 1}, 'subjective_score': 1, 'uncertainty_reduction': 1,
            'measurement_contract': {'contract_id': 'frozen-mean-control', 'source_id': task.identity.group_id,
                'data_version': task.identity.dataset_version, 'observable': 'mean', 'negative_control_id': 'subtract-self'}}
        jobs.append(job)
    core = {'identity': task.identity.data(), 'task_digest': task.content_hash, 'hard': hard, 'data_known': known,
        'measured_field': measured, 'construct_field': construct, 'control_target': 0.0, 'novelty': novelty, 'investment': investment,
        'publication_observation': {'field': 'x', 'mean': 2.0} if prior else None}
    cid = FrozenRecord.from_dict({'core': core, 'jobs': jobs, 'ratio': ratio}).content_hash
    for aid in authority.keys:
        for index,job in enumerate(jobs):
            authority.documents[(cid,aid,job['diagnostic_id'])] = {**core, 'observer': aid, 'job': job,
                'expected_mean': sum(float(row[measured]) for row in values) / len(values),
                'already_known': ratio and index > 4, 'main_threshold': 1.0 if index < 2 else 5.0}
    return {'source_id': task.identity.group_id, 'data_version': task.identity.dataset_version,
        'public_issue': 'Assess only the frozen observation and public construct; preserve uncertainty.', 'hard_constraint': hard,
        'authority_contract': {'contract_id': cid, 'source_id': task.identity.group_id,
            'authorities': [{'authority_id': aid, 'source_group': 'external-document-' + aid} for aid in authority.keys]}, 'jobs': jobs}


def _compile(tmp_path, monkeypatch, *, hard='none'):
    positive = tmp_path/'positive.csv'; positive.write_text('x,y\n1,-2\n3,0\n')
    tasks = {name: _task(name) for name in ('blade','discoverybench')}; authority = Authority(); bundles = {}
    for task in tasks.values():
        common = _item(task, positive, authority, count=8, ratio=True, hard=hard)
        q73 = {name: {**deepcopy(common), 'config': {'ratio_id': 'ratio_' + str(percent), 'exploration_percent': percent, 'control_percent': 25,
            'main_ids': ['job_' + str(i) for i in range(4)], 'diagnostic_ids': ['job_' + str(i) for i in range(4,8)]}}
            for name,percent in zip(VARIANTS['Q7.3'], (0,25,50,75))}
        q74 = {name: {**_item(task, positive, authority, count=2, bad=True, repaired=name != 'invalid_measure', hard=hard),
            'config': {'old_id':'job_0', 'repair_id':'job_1', 'instrument_id':'control-calibration'}} for name in VARIANTS['Q7.4']}
        specs = [('valid_known','x',True,'known','explore',True), ('novel_refuted','y',True,'novel','stop',False),
                 ('infeasible','x',False,'unknown','repair',False), ('easy_valid','x',True,'unknown','explore',False)]
        q75 = {name: {**_item(task,positive,authority,measured=field,construct=field,known=known,novelty=novelty,investment=investment,prior=prior,hard=hard),
            'config': {'observation_id':'job_0','observation_claim':'Mean of ' + field + ' is positive.', 'novelty_claim':'The measured observation is absent from prior publications.'}}
            for name,field,known,novelty,investment,prior in specs}
        q76 = {name: {**_item(task,positive,authority,measured=measured,construct=construct,hard=hard),
            'config': {'observation_id':'job_0','theory':'Mean of the intended field is positive.', 'construct':construct}}
            for name,measured,construct in [('contract_only','x','y'),('real_counterexample','y','y')]}
        bundles[task.content_hash] = freeze_extended_exploration_bundle(task, materials={'Q7.3':q73,'Q7.4':q74,'Q7.5':q75,'Q7.6':q76}, budget=FrozenRecord.from_dict(BUDGET))
    def inject(spec, variant, *, inputs):
        row = base_scenario(spec,variant,inputs=inputs).data()
        row['controller_input'] = extended_exploration_injection(spec.experiment_id,variant,task=inputs.task,evidence=inputs.evidence)
        return FrozenRecord.from_dict(row)
    monkeypatch.setattr(panel_plan,'scenario',inject)
    local = dict(panel_runner.DRIVERS)
    def resolver(task,bundle):
        return {'data_csv':positive}
    broker = DockerExecutionBroker([tmp_path])
    install_drivers(local,broker=broker,input_resolver=resolver,authority=authority)
    monkeypatch.setattr(panel_runner,'DRIVERS',local)
    package = CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]),changes={'prompt':{'instructions':'synthetic'}},search_cost=0)
    p0 = FrozenRecord.from_dict({'control':'fixed'}); scopes=tuple(VARIANTS)
    grids=obligation_grids(scopes,baseline_digest='f'*64,p0_control=p0)
    packages={arm.content_hash:package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled=compile_train_panel(stage='exploration',scope_ids=scopes,tasks=tuple(tasks.values()),evidence_by_task=bundles,budget=FrozenRecord.from_dict(BUDGET),
        baseline_digest='f'*64,p0_control=p0,packages_by_arm=packages,scorer=FrozenRecord.from_dict({'scorer':'none'}),acceptance_criteria=FrozenRecord.from_dict({'engineering':True}))
    return compiled,tasks,authority,bundles


def _model(seen, *, old_overclaim=False):
    def call(request):
        row=request.data(); seen.append(row); context=row['module_context']
        for forbidden in ('"variant"','"arm_id"','"enabled_modules"','external-document-', '"authorities"','"trusted_execution_material"','"publication_observation"'):
            assert forbidden not in request.encoded
        if row['slot']=='prospective':
            assert row['execution_feedback']==[]
            return FrozenRecord.from_dict({'assessment':'accept','rationale':'Frozen optimistic assessment before observations.'})
        if row['slot']=='semantic_review':
            actual=json.loads(context['observation']['stdout']) if context['observation'] else None
            concern=actual is not None and (actual['field']!=context['construct'] or actual['mean']<=0)
            # Deliberately observable anchoring susceptibility in this synthetic
            # model, determined from available context rather than module IDs.
            assessment='accept' if 'earlier_assessment' in context else 'concern' if concern else 'unknown'
            return FrozenRecord.from_dict({'assessment':assessment,'evidence_refs':[context['observation']['binding']] if actual else [],
                'counterexamples':['The observed field or mean does not support the declared theory.'] if concern else [],'uncertainty':'Synthetic construct review only.'})
        if row['slot']=='diagnostic':
            qualified=any(o.get('scientific_gate',{}).get('admitted') for o in context['observations'])
            return FrozenRecord.from_dict({'assessment':'qualified' if qualified else 'unresolved','rationale':'Only the exposed operation and observations inform this judgement.'})
        evidence=context['p0_evidence']; admitted=[x for x in evidence if x['admission']['admitted']]
        chosen=admitted[-1] if admitted else evidence[-1] if evidence else None
        if old_overclaim and evidence: chosen=evidence[0]
        outcome='positive' if old_overclaim else chosen['admission']['outcome'] if chosen and chosen['admission']['admitted'] else 'invalid' if chosen and chosen['admission']['state']['validity']=='invalid' else 'unknown'
        return FrozenRecord.from_dict({'objective_digest':context['required_objective_digest'],'outcome':outcome,
            'evidence_ids':[chosen['execution_digest']] if chosen else [],'conclusion':'Bounded public synthetic observation.','programme_complete':False})
    return call


def _run(compiled,tasks,cell,path,seen,**kwargs):
    return panel_runner.run_train_cell(cell,task=tasks[cell.identity.benchmark],scenario=compiled.scenarios[cell.key],package=compiled.packages[cell.runtime_arm.content_hash],
        objective=FrozenRecord.from_dict({'objective':'Mean of intended field is positive under calibrated control.'}),sidecar=path,model=_model(seen,**kwargs),audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}))


def _events(result): return [json.loads(line) for line in result.runtime.trace_path.read_text().splitlines()]


def test_freeze_all_88_opportunities_before_io(tmp_path,monkeypatch):
    compiled,tasks,authority,bundles=_compile(tmp_path,monkeypatch)
    assert len(compiled.panel.cells)==88 and authority.calls==[]
    for task in tasks.values(): assert len(freeze_ratio_selection(task,bundles[task.content_hash]).data()['ratio_ids'])==4


def test_actual_source_drift_is_zero_model_zero_verifier(tmp_path,monkeypatch):
    compiled,tasks,authority,bundles=_compile(tmp_path,monkeypatch)
    (tmp_path/'positive.csv').write_text('x,y\n777,777\n')
    seen=[]; result=_run(compiled,tasks,compiled.panel.cells[0],tmp_path/'run',seen)
    assert result.runtime.status=='failed' and seen==[] and authority.calls==[]


def test_ratio_menu_cannot_change_with_allocation(tmp_path,monkeypatch):
    _,tasks,authority,bundles=_compile(tmp_path,monkeypatch); task=next(iter(tasks.values())); body=bundles[task.content_hash].data()
    body['materials']['Q7.3']['high']['public_issue']='Changed task after ratio choice.'
    with pytest.raises(ContractError): freeze_extended_exploration_bundle(task,materials=body['materials'],budget=FrozenRecord.from_dict(BUDGET))


def test_ratios_must_change_actual_execution_allocation(tmp_path,monkeypatch):
    _,tasks,authority,bundles=_compile(tmp_path,monkeypatch); task=next(iter(tasks.values())); body=bundles[task.content_hash].data()
    for index,row in enumerate(body['materials']['Q7.3'].values()): row['config']['exploration_percent']=index+1
    with pytest.raises(ContractError): freeze_extended_exploration_bundle(task,materials=body['materials'],budget=FrozenRecord.from_dict(BUDGET))


def test_prior_art_observation_uses_real_task_ledger_contract():
    from types import SimpleNamespace
    from research_loop.modular.modules.evidence import EvidenceLedger,ClaimLedger
    task=_task('blade'); evidence=EvidenceLedger(task.identity); session=SimpleNamespace(task=task,evidence=evidence)
    bindings={'task':task.identity.task_id}
    root=_append_prior_observation(session,{'facets':{'prior_art_status':'matched'},'observation_digest':'a'*64,'admission':{'authorities':['a','b']}},bindings)
    claims=ClaimLedger(evidence)
    claim=claims.create('The measurement is novel.',subject_bindings=bindings)
    updated=claims.apply(claim.claim_id,{'subject_bindings':bindings,'supports':[],'refutes':[root.root_id]},expected_revision=claim.revision).claim
    assert updated.status=='refuted' and evidence.is_active_admitted(root.root_id)


@pytest.mark.parametrize('scope,variant',[('Q7.5','valid_known'),('Q7.6','contract_only'),('Q7.6','real_counterexample')])
def test_real_claim_and_review_seams_before_complete_grid(tmp_path,monkeypatch,scope,variant):
    compiled,tasks,authority,bundles=_compile(tmp_path,monkeypatch)
    candidates=[c for c in compiled.panel.cells if c.coverage_id==scope and c.variant==variant]
    cell=max(candidates,key=lambda c:len(c.runtime_arm.data()['enabled']))
    seen=[]; result=_run(compiled,tasks,cell,tmp_path/'run',seen)
    assert result.runtime.status=='succeeded',result.runtime.failure_reason


@pytest.mark.parametrize('hard',['resource','authorization'])
def test_typed_hard_missing_keeps_all_family_arm_denominators(tmp_path,monkeypatch,hard):
    compiled,tasks,authority,bundles=_compile(tmp_path,monkeypatch,hard=hard)
    (tmp_path/'positive.csv').unlink()  # No authority to read unavailable input.
    cells=[c for c in compiled.panel.cells if c.identity.benchmark=='blade' and c.variant==VARIANTS[c.coverage_id][0]]
    assert len(cells)==14
    for index,cell in enumerate(cells):
        seen=[]; result=_run(compiled,tasks,cell,tmp_path/'runs'/str(index),seen)
        assert result.runtime.status=='succeeded' and result.call_plan.data()['execution_attempts']==0
        assert result.call_plan.data()['model_calls']==LIMITS[cell.coverage_id][0]


def test_all_eight_ratio_inputs_checked_before_io(tmp_path,monkeypatch):
    compiled,tasks,authority,bundles=_compile(tmp_path,monkeypatch); cell=compiled.panel.cells[0]
    broker=panel_runner.DRIVERS[cell.coverage_id].broker; original=broker.validate_inputs; calls=[]
    def check(identity,inputs):
        calls.append(identity)
        if len(calls)==8: raise ContractError('eighth source changed')
        return original(identity,inputs)
    monkeypatch.setattr(broker,'validate_inputs',check)
    seen=[]; result=_run(compiled,tasks,cell,tmp_path/'run',seen)
    assert result.runtime.status=='failed' and len(calls)==8 and seen==[] and authority.calls==[]


@pytest.mark.parametrize('fault',['partial_known','partial_unknown'])
def test_partial_transport_cost_is_persisted_before_failure(tmp_path,monkeypatch,fault):
    compiled,tasks,authority,bundles=_compile(tmp_path,monkeypatch); authority.fault=fault
    seen=[]; result=_run(compiled,tasks,compiled.panel.cells[0],tmp_path/'run',seen); events=_events(result)
    assert result.runtime.status=='failed' and len(seen)==1
    assert any(e['stage']=='extended_verifier_partial_response' for e in events)
    failure=next(e['data'] for e in events if e['stage']=='extended_verifier_failure')
    assert failure['cost']['units'] is None and failure['exception_reported_cost']['units']==(2 if fault=='partial_known' else None)


def test_full_88_cell_real_docker_grid(tmp_path,monkeypatch):
    compiled,tasks,authority,bundles=_compile(tmp_path,monkeypatch); runs=[]; measurements=[]
    for index,cell in enumerate(compiled.panel.cells):
        seen=[]; result=_run(compiled,tasks,cell,tmp_path/'runs'/str(index),seen)
        assert result.runtime.status=='succeeded', (index,result.runtime.failure_reason)
        assert result.call_plan.data()['model_calls']==LIMITS[cell.coverage_id][0]
        assert result.call_plan.data()['execution_attempts']==LIMITS[cell.coverage_id][1]
        context=next(r['module_context'] for r in seen if r['slot']=='diagnostic'); enabled=cell.runtime_arm.data()['enabled']
        assert all(('scientific_gate' in o)==('M1' in enabled) for o in context['observations'])
        operation=context['operation']
        if cell.coverage_id=='Q7.3':
            ratio=operation['ratio_measurement']; expected=25 if 'M7' not in enabled else {'zero':0,'low':25,'medium':50,'high':75}[cell.variant]
            assert ratio['allocation']['effective_percent']==expected
        elif cell.coverage_id=='Q7.4':
            repair=operation['instrument_repair']; assert repair['old_active_admitted'] is False
            assert (repair['repair'] is not None)==('M1' in enabled)
            assert len(context['observations'])==2
        elif cell.coverage_id=='Q7.5':
            assert ('claims' in operation)==('M2' in enabled)
            if 'M2' in enabled and cell.variant=='valid_known':
                assert operation['claims']['measurement_root_retained'] is True
                assert operation['claims']['novelty']['status']=='refuted'
            if 'M1' in enabled:
                expected={'valid_known':('valid','supported','known','explore'), 'novel_refuted':('valid','refuted','novel','stop'),
                    'infeasible':('unknown','undetermined','unknown','repair'), 'easy_valid':('valid','supported','unknown','explore')}[cell.variant]
                state=context['observations'][0]['scientific_gate']['state']
                assert tuple(state[k] for k in ('validity','support','novelty','investment'))==expected
        else:
            review=next(r['module_context'] for r in seen if r['slot']=='semantic_review')
            assert ('earlier_assessment' in review)==('M5' not in enabled)
            assert operation['semantic_review']['response']['assessment']==('concern' if 'M5' in enabled else 'accept')
        events=_events(result); response=next(e['data']['response'] for e in reversed(events) if e['stage']=='model_response')
        assert events[-1]['data']['candidate_digest']==FrozenRecord.from_dict(response).content_hash
        measurements.append({'index':index,'cell':cell.data(),'trace_sha256':sha256(result.runtime.trace_path.read_bytes()).hexdigest(),
            'trace_path':str(result.runtime.trace_path),'trace_digest':result.runtime.trace_digest,'operation':operation})
        runs.append(result.runtime)
    assert PanelReceiptVerifier().verify(compiled.panel,tuple(runs)).observed_cells==88
    with pytest.raises(ContractError):
        select_training_ratio(task=next(iter(tasks.values())),bundle=next(iter(bundles.values())),panel=compiled.panel,runtimes=runs[:-1])
    selections=[]
    for task in tasks.values():
        selected=select_training_ratio(task=task,bundle=bundles[task.content_hash],panel=compiled.panel,runtimes=runs)
        assert selected.data()['selected_ratio_id']=='ratio_25'; selections.append(selected.data())
    (tmp_path/'main-grid-manifest.json').write_text(json.dumps({'cells':measurements,'ratio_selections':selections},indent=2))


def test_old_invalid_execution_cannot_be_redeemed_by_repair(tmp_path,monkeypatch):
    compiled,tasks,authority,bundles=_compile(tmp_path,monkeypatch)
    cell=next(c for c in compiled.panel.cells if c.coverage_id=='Q7.4' and c.variant=='old_evidence' and {'M1','M7'}<=set(c.runtime_arm.data()['enabled']))
    seen=[]; result=_run(compiled,tasks,cell,tmp_path/'run',seen,old_overclaim=True)
    assert result.runtime.status=='blocked'
    assert _events(result)[-1]['data']['reasons']==['missing_validated_evidence']


@pytest.mark.parametrize('kind',['input','program'])
def test_actual_bytes_drift_before_trusted_observation(tmp_path,monkeypatch,kind):
    compiled,tasks,authority,bundles=_compile(tmp_path,monkeypatch); cell=compiled.panel.cells[0]
    broker=panel_runner.DRIVERS[cell.coverage_id].broker; original=broker.execute
    def drift(request):
        receipt=original(request)
        (tmp_path/'positive.csv' if kind=='input' else request.program).write_text('changed after execution')
        return receipt
    monkeypatch.setattr(broker,'execute',drift)
    seen=[]; result=_run(compiled,tasks,cell,tmp_path/'run',seen)
    assert result.runtime.status=='failed' and len(authority.calls)==1 and len(seen)==1


def test_semantic_failure_cannot_coexist_with_valid_audit(tmp_path,monkeypatch):
    compiled,tasks,authority,bundles=_compile(tmp_path,monkeypatch); authority.fault='false_semantic'
    seen=[]; result=_run(compiled,tasks,compiled.panel.cells[0],tmp_path/'run',seen)
    assert result.runtime.status=='failed' and len(authority.calls)==2 and len(seen)==1
