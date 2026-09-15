"""Precommit a common C5 TRAIN comparison without reinterpreting old scores.

These are new common-procedure compositions. An alias records which earlier
factor setting motivated a composition; it is not an authenticated old build.
The lock authorizes neither execution nor selection, validation or deployment.
"""
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
import hashlib

from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.experiments import registry
from research_loop.modular.full_loo_composition import (
    MODULES, SCHEMA, _arm, derive_allocation)
from research_loop.modular.full_loo_modules import model_schemas
from research_loop.modular.joint_deployment import JointComponentVersion, _hash, _path
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.modular.panel_receipts import REQUIRED_TRIPLES
from research_loop.modular.phase_provider import validate_configuration
from research_loop.modular.train_selection import FrozenTrainSelectionRule
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.ontology import ContractError

OBLIGATION = 'c5-common-joint-train-v1'
HEADLESS_OBLIGATION = 'c5-common-joint-train-headless-evaluator-v1'
_HEADLESS_PROVIDER_KIND = 'grok-headless-frozen-evaluator-v1'
_HEADLESS_USAGE_SCHEMA = 'c5-headless-evaluator-usage-declaration-v1'
_HEADLESS_USAGE_CONTRACT = 'grok-headless-c5-usage-v1'
R = FrozenRecord.from_dict


def _digest(value, field):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ContractError(f'{field} must be a sha256 digest')
    return value


def _headless_evaluator_binding(usage, provider):
    """Validate the public C5 declaration without constructing a private worker."""
    usage_fields = {'schema', 'provider_kind', 'usage_contract', 'evaluator_config_digest'}
    provider_fields = {'kind', 'configuration_digest'}
    if (not isinstance(usage, dict) or set(usage) != usage_fields
            or usage.get('schema') != _HEADLESS_USAGE_SCHEMA
            or usage.get('provider_kind') != _HEADLESS_PROVIDER_KIND
            or usage.get('usage_contract') != _HEADLESS_USAGE_CONTRACT):
        raise ContractError('C5 headless evaluator usage declaration is malformed')
    _digest(usage.get('evaluator_config_digest'), 'C5 evaluator usage declaration')
    if (not isinstance(provider, dict) or set(provider) != provider_fields
            or provider.get('kind') != _HEADLESS_PROVIDER_KIND):
        raise ContractError('C5 headless evaluator provider descriptor is malformed')
    _digest(provider.get('configuration_digest'), 'C5 evaluator provider descriptor')
    # C5 names the exact immutable worker configuration already checked by the
    # startup handshake and authenticated by the signed evaluator closure.
    # A second unrelated digest would only be an unverified caller assertion.
    if usage['evaluator_config_digest'] != provider['configuration_digest']:
        raise ContractError('C5 evaluator usage must bind the actual worker configuration')
    return dict(usage), dict(provider)


def common_recipes(*, baseline_digest, history_binding_digest, builder_digest, context_bytes):
    """Union all legal C1/C2/C3/C4 settings under one *new* procedure.

    Only identical complete generated recipes share an alias. The source
    experiments, Q variants and their distinct builds remain separate work.
    """
    for value in (baseline_digest, history_binding_digest, builder_digest):
        _hash(value, 'common recipe input')
    if type(context_bytes) is not int or context_bytes < 1:
        raise ContractError('positive common context allocation required')
    compatibility = default_compatibility(baseline_digest)
    origins, unavailable = {}, []
    designs = [('C1:' + m, compatibility.conditional_factorial((m,))) for m in MODULES]
    designs += [('C2:' + '+'.join(p), compatibility.conditional_factorial(p))
                for p in combinations(MODULES, 2)]
    designs += [('C3:' + '+'.join(p), compatibility.conditional_factorial(p)) for p in REQUIRED_TRIPLES]
    designs += [('C4', compatibility.leave_one_out(MODULES))]
    common = dict(history_binding_digest=history_binding_digest, builder_digest=builder_digest,
                  history_input_budget=context_bytes, schema=SCHEMA)
    for design_id, design in designs:
        for cell in design.data()['cells']:
            alias = design_id + '/' + cell['id']
            if cell['status'] != 'executable':
                # Rebuild a canonical reason; never inherit set iteration order.
                active = (set(MODULES) - {cell['id'].removeprefix('without-')}
                          if design_id == 'C4' else set(design.data()['background']) |
                          {m for m, bit in zip(design.data()['factors'], cell['levels'], strict=True) if bit})
                missing = [{'module': s['id'], 'requires': sorted(set(s['requires']) - active)}
                           for s in compatibility.manifest().data()['modules']
                           if s['id'] in active and set(s['requires']) - active]
                unavailable.append({'origin': alias, 'status': 'structurally_unavailable', 'missing': missing})
                continue
            active = cell['arm']['enabled']
            procedure = 'common_joint_composition' if active else 'ordinary_matched_control'
            recipe = _arm(arm_id='unassigned', procedure=procedure, enabled=active,
                          comparison='common_pipeline_vs_matched_ordinary', **common)
            # Identity includes every generated operation, boundary and budget.
            key = R(recipe).content_hash
            row = origins.setdefault(key, {'recipe': recipe, 'origins': []})
            row['origins'].append(alias)
    rows = []
    for key, row in sorted(origins.items()):
        recipe = row['recipe']
        recipe['id'] = ('ordinary-control' if recipe['procedure'] == 'ordinary_matched_control'
                        else 'joint-' + key)
        rows.append({'recipe': recipe, 'origins': sorted(row['origins']),
                     'source_identity': 'new_common_procedure_projection_requires_execution'})
    rows.sort(key=lambda row: (row['recipe']['id'] != 'ordinary-control', row['recipe']['id']))
    b0 = _arm(arm_id='B0', procedure='baseline_b0', enabled=(), comparison='separate_budget_reference', **common)
    rows.append({'recipe': b0, 'origins': ['C4/B0'],
                 'source_identity': 'new_common_procedure_projection_requires_execution'})
    return R({'schema': 'c5-common-recipe-catalogue-v1', 'recipes': rows,
              'structural_origins': unavailable, 'score_based_pruning': False,
              'source_scores_reusable': False, 'original_experiments_completed': False})


def _subject(identity): return identity.benchmark, identity.group_id


def _binding(task, path):
    if type(task) is not PublicTask:
        raise ContractError('exact public TRAIN task required')
    task.identity.require_train()
    raw = Path(path).read_bytes()
    return {'identity': task.identity.data(), 'task_digest': task.content_hash,
            'csv_sha256': hashlib.sha256(raw).hexdigest(), 'csv_byte_count': len(raw)}


@dataclass(frozen=True)
class FrozenJointTrainProtocol:
    record: FrozenRecord

    def __post_init__(self):
        if type(self.record) is not FrozenRecord:
            raise ContractError('exact C5 common TRAIN lock required')
        b = self.record.data()
        fields = {'schema', 'domain', 'baseline_digest', 'p0_digest', 'runtime_sources',
                  'history', 'targets', 'builder_digest', 'history_binding_digest', 'component_templates',
                  'context_bytes', 'catalogue', 'allocation', 'provider_config', 'scorer', 'selection_rule',
                  'issue_contracts', 'replicate', 'execution_authorized', 'acceptance_authorized'}
        headless = b.get('schema') == HEADLESS_OBLIGATION
        expected_fields = fields | ({'evaluator_usage', 'evaluator_provider'} if headless else set())
        if (set(b) != expected_fields or b['schema'] not in {OBLIGATION, HEADLESS_OBLIGATION} or b['domain'] != 'train'
                or b['replicate'] != 'r1' or b['execution_authorized'] is not False
                or b['acceptance_authorized'] is not False):
            raise ContractError('C5 common protocol schema or authority drift')
        if headless:
            _headless_evaluator_binding(b['evaluator_usage'], b['evaluator_provider'])
        for name in ('baseline_digest', 'p0_digest', 'builder_digest', 'history_binding_digest'):
            _hash(b[name], name)
        sources = b['runtime_sources']
        if not isinstance(sources, dict) or not sources:
            raise ContractError('common runtime source manifest required')
        for name, value in sources.items(): _path(name); _hash(value, 'runtime source')
        bindings = [b['history'], *b['targets']]
        if not b['targets']:
            raise ContractError('common TRAIN targets required')
        identities = []
        for row in bindings:
            if set(row) != {'identity', 'task_digest', 'csv_sha256', 'csv_byte_count'}:
                raise ContractError('exact original public data binding required')
            identity = DataIdentity.parse(row['identity']); identity.require_train(); identities.append(identity)
            for name in ('task_digest', 'csv_sha256'): _hash(row[name], name)
            if type(row['csv_byte_count']) is not int or row['csv_byte_count'] < 1:
                raise ContractError('nonempty original public CSV required')
        if (len(set(identities)) != len(identities) or len({i.split_id for i in identities}) != 1
                or len({row['task_digest'] for row in bindings}) != len(bindings)
                or _subject(identities[0]) in {_subject(i) for i in identities[1:]}
                or not {'blade', 'discoverybench'} <= {i.benchmark for i in identities[1:]}):
            raise ContractError('common TRAIN subjects, split or primary benchmark coverage drift')
        if set(b['component_templates']) != set(MODULES):
            raise ContractError('all nine independently addressed component templates required')
        for name, value in b['component_templates'].items():
            component = JointComponentVersion(R(value))
            manifest = TrainingManifest(R(value['training_manifest']))
            if component.module_id != name or set(manifest.identities()) != {identities[0]}:
                raise ContractError('component templates may expose only the fixed TRAIN history')
        catalogue = common_recipes(baseline_digest=b['baseline_digest'], history_binding_digest=b['history_binding_digest'],
                                  builder_digest=b['builder_digest'], context_bytes=b['context_bytes'])
        if catalogue.data() != b['catalogue']:
            raise ContractError('common candidate catalogue, aliases or boundaries drift')
        recipes = [row['recipe'] for row in b['catalogue']['recipes']]
        if b['allocation'] != derive_allocation(recipes, target_count=len(b['targets'])):
            raise ContractError('common prospective resource denominator drift')
        validate_configuration(R(b['provider_config']), schemas=model_schemas(),
                               main_opportunities=b['allocation']['model_calls'])
        scorer = ScorerConfig(R(b['scorer']))
        # ScorerConfig's constructor itself is intentionally a lightweight wrapper.
        s = scorer.record.data()
        if (ScorerConfig.create(**{k: s[k] for k in ('benchmark', 'evaluator_id', 'rubric_digest', 'version')}).record
                != scorer.record or set(scorer.benchmarks) != {'blade', 'discoverybench'}):
            raise ContractError('canonical scorer configuration required')
        rule = FrozenTrainSelectionRule(R(b['selection_rule'])).record.data()
        if (rule['coverage_id'] != OBLIGATION or rule['baseline_arm'] != 'ordinary-control'
                or set(rule['tie_break_order']) != {r['id'] for r in recipes if r['id'] != 'B0'}):
            raise ContractError('TRAIN ranking must cover every matched candidate and exclude unequal-budget B0')
        if b['issue_contracts'] != {name: spec.record.data() for name, spec in registry().items()}:
            raise ContractError('all 48 original issue and variant contracts must remain separate')

    @property
    def digest(self): return self.record.content_hash

    def trial_binding(self, recipe_id, task_digest):
        """A bare recipe alias never identifies a build or result across locks."""
        self.__post_init__()
        b = self.record.data()
        if (recipe_id not in {r['recipe']['id'] for r in b['catalogue']['recipes']}
                or task_digest not in {r['task_digest'] for r in b['targets']}):
            raise ContractError('trial must bind an exact frozen common recipe and TRAIN target')
        return R({'schema': 'c5-common-train-trial-binding-v1', 'protocol_digest': self.digest,
                  'recipe_id': recipe_id, 'task_digest': task_digest, 'replicate': b['replicate']})

    @classmethod
    def freeze(cls, *, baseline_digest, p0_digest, runtime_sources, history, targets, public_csv,
               builder_digest, history_binding_digest, component_templates, context_bytes,
               provider_config, scorer, selection_rule, evaluator_usage=None, evaluator_provider=None):
        targets = tuple(targets)
        if any(type(v) is not JointComponentVersion for v in component_templates.values()):
            raise ContractError('exact independently versioned templates required')
        if type(scorer) is not ScorerConfig or type(selection_rule) is not FrozenTrainSelectionRule:
            raise ContractError('typed scorer and predeclared TRAIN selection rule required')
        headless = evaluator_usage is not None or evaluator_provider is not None
        if headless:
            evaluator_usage, evaluator_provider = _headless_evaluator_binding(evaluator_usage, evaluator_provider)
        tasks = (history, *targets)
        if set(public_csv) != {t.content_hash for t in tasks}:
            raise ContractError('only exact common history/target public CSV inputs permitted')
        catalogue = common_recipes(baseline_digest=baseline_digest, history_binding_digest=history_binding_digest,
                                  builder_digest=builder_digest, context_bytes=context_bytes)
        return cls(R({'schema': HEADLESS_OBLIGATION if headless else OBLIGATION, 'domain': 'train', 'baseline_digest': baseline_digest,
            'p0_digest': p0_digest, 'runtime_sources': dict(runtime_sources), 'builder_digest': builder_digest,
            'history_binding_digest': history_binding_digest, 'history': _binding(history, public_csv[history.content_hash]),
            'targets': [_binding(t, public_csv[t.content_hash]) for t in targets], 'context_bytes': context_bytes,
            'component_templates': {k: v.record.data() for k, v in component_templates.items()},
            'catalogue': catalogue.data(), 'allocation': derive_allocation(
                [r['recipe'] for r in catalogue.data()['recipes']], target_count=len(targets)),
            'provider_config': provider_config.data(), 'scorer': scorer.record.data(),
            **({'evaluator_usage': evaluator_usage, 'evaluator_provider': evaluator_provider} if headless else {}),
            'selection_rule': selection_rule.record.data(), 'replicate': 'r1',
            'issue_contracts': {name: spec.record.data() for name, spec in registry().items()},
            'execution_authorized': False, 'acceptance_authorized': False}))

    def verify_original_inputs(self, *, tasks, public_csv, component_roots, runtime_root):
        self.__post_init__()
        b = self.record.data(); bindings = [b['history'], *b['targets']]
        if set(tasks) != set(public_csv) or set(tasks) != {r['task_digest'] for r in bindings}:
            raise ContractError('original task/input inventory drift')
        for row in bindings:
            if _binding(tasks[row['task_digest']], public_csv[row['task_digest']]) != row:
                raise ContractError('original public task/CSV drift')
        if set(component_roots) != set(MODULES):
            raise ContractError('exact component source roots required')
        for name, component in b['component_templates'].items():
            JointComponentVersion(R(component)).verify_sources(component_roots[name])
        root = Path(runtime_root).resolve(strict=True)
        for name, expected in b['runtime_sources'].items():
            path = (root / name).resolve(strict=True)
            if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ContractError('original common runtime source drift')

    def write_lock(self, path, **original_inputs):
        """Recheck original bytes, then write one immutable prospective lock."""
        self.verify_original_inputs(**original_inputs)
        with Path(path).open('xb') as stream:
            stream.write(self.record.encoded.encode('utf-8'))
