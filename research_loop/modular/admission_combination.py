"""Subject-bound M1 qualification in the existing lineage/solver session."""
import json
import re

from evaluation.modular.combination_scoring import _signed_body, _score_input_payload
from research_loop.modular.contracts import FrozenRecord, DataIdentity
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial, DualMaterialVerifier
from research_loop.modular.modules.admission import EvidenceAdmission, ScientificState, AuditItem
from research_loop.modular.modules.context import ContextBuilder
from research_loop.ontology import ContractError

DESIGNS = {'pair:M1+M2': ('M1', 'M2'), 'pair:M1+M3': ('M1', 'M3'), 'pair:M1+M5': ('M1', 'M5')}


def registered_design(name, baseline):
    if name not in DESIGNS: raise ContractError('unsupported admission combination')
    return default_compatibility(baseline).conditional_factorial(DESIGNS[name])


class FrozenAdmissionMaterial(FrozenLineageMaterial):
    def __post_init__(self):
        if not isinstance(self.record, FrozenRecord): raise ContractError('frozen admission material required')
        b = self.data(); base = {k: v for k, v in b.items() if k != 'qualification_observations'}
        if b.get('schema') != 'admission-combination-material-v1': raise ContractError('admission material schema')
        base['schema'] = 'lineage-combination-material-v1'
        FrozenLineageMaterial(FrozenRecord.from_dict(base))
        q = b.get('qualification_observations')
        if (len(self.record.encoded.encode('utf-8')) > 262144 or b['withdrawals'] != []
                or not isinstance(q, dict) or set(q) != {'before', 'after'}):
            raise ContractError('qualification phases replace scripted withdrawals')
        keys = {r['key'] for r in b['originals']}
        for phase in q.values():
            if (not isinstance(phase, dict) or set(phase) != keys
                    or any(not isinstance(v, dict) or not v for v in phase.values())):
                raise ContractError('qualification observations must cover exact originals in both phases')
        public = {k: b[k] for k in ('originals','representations','claims','question','ordinary_summary')}
        def check(v):
            if isinstance(v, dict): return all(check(k) and check(x) for k,x in v.items())
            if isinstance(v, list): return all(check(x) for x in v)
            return not isinstance(v, str) or not re.search(r'(?i)(\bM[1-9]\b|\bQ\d+\.\d+\b|arm_id|expected_correct|source_group|gold|validation|[A-Z]:[\\/]|/input/)', v)
        if not check(public): raise ContractError('public material contains experiment labels or host paths')
        for row in b['originals']:
            if row['subject_bindings'].get('task') != b['identity']['task_id']:
                raise ContractError('each observation must bind this exact train task')
        by_key = {r['key']: r for r in b['originals']}
        for claim in b['claims']:
            if any(by_key[k]['subject_bindings'] != claim['subject_bindings'] for k in claim['supports']+claim['refutes']):
                raise ContractError('claim relations require the same exact observation subject')
        root_ids = [FrozenRecord.from_dict({'root': r['root_material'], 'bindings': r['subject_bindings']}).content_hash for r in b['originals']]
        if len(set(root_ids)) != len(root_ids): raise ContractError('duplicate originals must be explicit representations')

    def subjects(self):
        b = self.data()
        return {phase: {r['key']: FrozenRecord.from_dict({'identity': b['identity'], 'task_digest': b['task_digest'],
            'public_artifacts': b['public_artifacts'], 'observation': r, 'phase': phase,
            'qualification_observation': obs[r['key']]}).content_hash for r in b['originals']}
            for phase, obs in b['qualification_observations'].items()}


def _assessment(row, subject):
    if (not isinstance(row, dict) or set(row) != {'subject_digest','state','outcome','execution_success','audit'}
            or row['subject_digest'] != subject or type(row['execution_success']) is not bool
            or row['outcome'] not in {'positive','negative'} or not isinstance(row['state'], dict)
            or set(row['state']) != {'validity','support','novelty','investment'}
            or not isinstance(row['audit'], list) or len(row['audit']) != 1
            or not isinstance(row['audit'][0], dict) or set(row['audit'][0]) != {'name','executed','passed'}
            or row['audit'][0]['name'] != 'measurement'):
        raise ContractError('qualification needs exact scientific subject, state and audit')
    try:
        ScientificState(**row['state']); AuditItem(**row['audit'][0])
    except (TypeError, ValueError) as exc: raise ContractError('invalid qualification types') from exc


class AdmissionMaterialVerifier(DualMaterialVerifier):
    def request(self, material, cell_binding):
        if type(material) is not FrozenAdmissionMaterial: raise ContractError('typed admission subjects required')
        b = super().request(material, cell_binding).data()
        b.update(schema='admission-material-request-v1', subjects=material.subjects())
        return FrozenRecord.from_dict(b)

    def _response(self, authority, request, response):
        b = _signed_body(response, {authority.authority.authority_id: authority.authority.key}, message='admission qualification')
        if (set(b) != {'schema','authority','request_digest','material_digest','identity','source_group','verdict','cost_units','assessments'}
                or b['schema'] != 'admission-material-response-v1' or b['request_digest'] != request.content_hash
                or b['material_digest'] != request.data()['material_digest'] or b['identity'] != request.data()['material']['identity']
                or b['source_group'] != authority.source_group or b['verdict'] not in {'verified','rejected','unknown'}
                or b['cost_units'] is not None and (type(b['cost_units']) is not int or not 0 <= b['cost_units'] <= self.cost_limit_per_call)):
            raise ContractError('qualification authority subject or accounting drift')
        values = b['assessments']; subjects = request.data()['subjects']
        if not isinstance(values, dict) or set(values) != set(subjects): raise ContractError('qualification phases missing')
        for phase, originals in subjects.items():
            if not isinstance(values[phase], dict) or set(values[phase]) != set(originals): raise ContractError('qualification originals missing')
            for key, subject in originals.items(): _assessment(values[phase][key], subject)
        return b

    def replay(self, material, path, *, cell_binding):
        digest = super().replay(material, path, cell_binding=cell_binding)
        rows = json.loads(path.read_text(encoding='utf-8'))['calls']
        if FrozenRecord.from_dict(rows[0]['response']['body']['assessments']) != FrozenRecord.from_dict(rows[1]['response']['body']['assessments']):
            raise ContractError('two independent qualification observations disagree')
        return digest

    def assessments(self, material, path, *, cell_binding):
        self.replay(material, path, cell_binding=cell_binding)
        return json.loads(path.read_text(encoding='utf-8'))['calls'][0]['response']['body']['assessments']


def transition(evidence, claims, cache, material, enabled, qualification):
    if qualification is None: raise ContractError('actual qualification receipts required before admission')
    b = material.data(); sources = {r['key']: r for r in b['originals']}; decisions = {}
    for phase in ('before','after'):
        decisions[phase] = {}
        for key, r in sources.items():
            q = qualification[phase][key]; _assessment(q, material.subjects()[phase][key])
            if 'M1' in enabled:
                decision = EvidenceAdmission.decide(identity=evidence.identity, state=ScientificState(**q['state']),
                    outcome=q['outcome'], execution_success=q['execution_success'], trusted_validator='configured-source-quorum',
                    validator_verified=True, evidence_ids=[key], subject_bindings=r['subject_bindings'],
                    required_audit=('measurement',), audit=[AuditItem(**a) for a in q['audit']])
                decisions[phase][key] = {'admitted': decision.admitted, 'reason': decision.reason, 'subject_digest': q['subject_digest']}
            else: decisions[phase][key] = {'admitted': False, 'reason': 'ordinary_unqualified_buffer', 'subject_digest': q['subject_digest']}
    rows = [(r['key'], r['key'], 'raw', r['content']) for r in b['originals']]
    rows += [(r['key'], r['root'], r['representation'], r['content']) for r in b['representations']]
    roots, relations = {}, {}
    if 'M2' in enabled:
        for key, origin, representation, content in rows:
            r = sources[origin]
            record = evidence.append({'kind':'observation','root_material':r['root_material'],'content':content,
                'subject_bindings':r['subject_bindings'],'independent_group':evidence.identity.group_id,'representation':representation},
                {'trusted_validator':qualification['before'][origin]['subject_digest'],
                 'validator_verified':True,'admitted':decisions['before'][origin]['admitted']})
            roots[key] = record.root_id
        for row in b['claims']:
            claim = claims.create(row['statement'], subject_bindings=row['subject_bindings']); relations[row['key']] = claim.claim_id
            claims.apply(claim.claim_id, {'supports':[roots[k] for k in row['supports'] if decisions['before'][k]['admitted']],
                'refutes':[roots[k] for k in row['refutes'] if decisions['before'][k]['admitted']], 'subject_bindings':row['subject_bindings']}, expected_revision=0)
            if row['depends_on']:
                claim = next(c for c in claims.claims() if c.claim_id == claim.claim_id)
                claims.link_dependencies(claim.claim_id,[relations[k] for k in row['depends_on']],expected_revision=claim.revision)
    before = claims.snapshot(); builder = ContextBuilder(evidence.identity, budget_bytes=b['context_budget_bytes'])
    mode = 'candidate' if 'M3' in enabled else 'baseline'
    prior = cache.get_or_build(builder,b['question'],evidence,claims,mode=mode,baseline_summary=b['ordinary_summary'])
    revoked = [k for k in sources if decisions['before'][k]['admitted'] and not decisions['after'][k]['admitted']]
    if 'M2' in enabled:
        for key in revoked: evidence.withdraw(roots[key], 'Subject-bound source requalification no longer admits this observation.')
        claims.refresh_after_withdrawal()
    current = cache.get_or_build(builder,b['question'],evidence,claims,mode=mode,baseline_summary=b['ordinary_summary'])
    if 'M3' in enabled:
        cache._items.clear(); cache.get_or_build(builder,b['question'],evidence,claims,mode=mode,baseline_summary=b['ordinary_summary'])
    visible = [(key, origin, content) for key,origin,_,content in rows if 'M1' not in enabled or
               decisions['before'][origin]['admitted'] and decisions['after'][origin]['admitted']]
    if 'M2' in enabled:
        live = {r.root_id:r for r in evidence.roots(admitted_only='M1' in enabled)}
        observations = [{'binding':k,'content':r.payload.data()['content']} for k,r in live.items()]
    else:
        observations = [{'binding':FrozenRecord.from_dict({'observation_key':key}).content_hash,'content':content} for key,_,content in visible]
    entries = current.entries.data()['entries']
    for entry in entries:
        if entry.get('kind') == 'evidence':
            entry['payload'] = {k:v for k,v in entry['payload'].items() if k not in {'trusted_validator','validator_verified'}}
    public = FrozenRecord.from_dict({'observations':observations,'memory':entries})
    if len(public.encoded.encode('utf-8')) > b['context_budget_bytes']: raise ContractError('admission public context exceeds budget')
    return FrozenRecord.from_dict({'material_digest':material.record.content_hash,'raw_representation_denominator':len(rows),
        'root_denominator':len(sources),'decisions':decisions,'revoked':revoked,'root_bindings':roots,'claim_bindings':relations,
        'before_claims':before.data(),'after_claims':claims.snapshot().data(),'evidence':evidence.snapshot().data(),
        'context_before':prior.data(),'context_after':current.data(),'context_before_digest':prior.content_hash,
        'context_after_digest':current.content_hash,'public':public.data(),'public_digest':public.content_hash,
        'public_bytes':len(public.encoded.encode('utf-8')),'context_budget_bytes':b['context_budget_bytes']})


def issue_admission_score_input(*, authority, result, **args):
    from research_loop.modular.lineage_combination_driver import verify_lineage_combination_cell
    from evaluation.modular.linked_scoring import LinkedExecutionAuthority
    if (not isinstance(authority, LinkedExecutionAuthority) or args.get('panel') is None
            or args['panel'].obligation_id not in DESIGNS or type(args.get('material')) is not FrozenAdmissionMaterial):
        raise ContractError('admission score issuer requires its exact family and qualified material')
    verify_lineage_combination_cell(result, **args)
    return authority.issue(_score_input_payload(args['panel'], result).data())
