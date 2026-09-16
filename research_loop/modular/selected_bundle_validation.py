"""Fixed C4/C5 acceptance subjects; no search, selection, builder or Q promotion.

The independently configured TRAIN freeze authority must replay the original
selection before signing. This module only consumes that immutable statement.
The envelope is a trust boundary, not evidence of an operator's independence.
"""
from dataclasses import dataclass
from types import MappingProxyType

from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_composition import MODULES, SCHEMA, _arm
from research_loop.modular.full_loo_modules import slots
from research_loop.modular.joint_deployment import JointDeploymentBundle, _hash
from research_loop.modular.joint_train_runtime import CONSUMERS, ROOT, runtime_sources
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import FrozenPanel, PanelCell, verify_signed
from research_loop.ontology import ContractError

R = FrozenRecord.from_dict
SCOPES = {'C4': 'C4-final-bundle', 'C5': 'C5-final-bundle'}


def bundle_spec(bundle):
    """Consume all nine component configs/states, not an acknowledgement hash."""
    if type(bundle) is not JointDeploymentBundle:
        raise ContractError('exact independently frozen deployment bundle required')
    bundle.__post_init__()
    b = bundle.record.data(); schedule = b['resource_schedule']
    if (set(schedule) != {'schema', 'recipe', 'slots', 'context_budget_bytes', 'timeout_seconds'}
            or schedule['schema'] != 'c5-selected-target-schedule-v1'
            or set(b['components']) != set(MODULES)
            or type(schedule['context_budget_bytes']) is not int or not 1024 <= schedule['context_budget_bytes'] <= 65536
            or type(schedule['timeout_seconds']) is not int or not 1 <= schedule['timeout_seconds'] <= 120):
        raise ContractError('fixed selected bundle lacks nine components or bounded target schedule')
    recipe = schedule['recipe']
    if (not isinstance(recipe, dict) or recipe.get('procedure') not in
            {'baseline_b0', 'ordinary_matched_control', 'full_bundle', 'full_loo', 'common_joint_composition'}
            or recipe.get('status') != 'executable' or set(recipe.get('arm_bits', {})) != set(MODULES)
            or any(type(v) is not int or v not in (0, 1) for v in recipe['arm_bits'].values())):
        raise ContractError('fixed executable recipe required; VAL cannot select a recipe')
    active = [m for m, v in recipe['arm_bits'].items() if v]
    expected = _arm(arm_id=recipe['id'], procedure=recipe['procedure'], enabled=active,
        comparison=recipe['comparison'], history_binding_digest=recipe['history_binding_digest'],
        builder_digest=recipe['builder_digest'], history_input_budget=recipe['history_input_budget'],
        schema=SCHEMA, removal=recipe.get('removed_module'))
    if recipe != expected or schedule['slots'] != list(slots(recipe, 'target')):
        raise ContractError('frozen recipe differs from its native operation schedule')
    package = None; selection = None; provenance = None
    for name, component in bundle.components().items():
        value = component.record.data(); config, state = value['config'], value['state']
        wanted = {'schema': 'c5-fixed-stage-consumer-v1', 'module_id': name,
                  'consumer': CONSUMERS[name], 'pipeline': 'full_loo_modules-v1'}
        if (set(config) != {'schema', 'module_id', 'template_digest', 'consumer_config', 'history_build_level', 'target_level'}
                or config['schema'] != 'c5-selected-component-consumer-v1' or config['module_id'] != name
                or config['consumer_config'] != wanted
                or config['history_build_level'] != recipe['history_build_levels'][name]
                or config['target_level'] != recipe['target_levels'][name]
                or set(state) != {'schema', 'template_state', 'selected_package', 'selection_digest', 'history_receipt_digest'}
                or state['schema'] != 'c5-selected-component-state-v1'):
            raise ContractError('selected component is not the native fixed consumer')
        for field in ('template_digest',): _hash(config[field], field)
        for field in ('selection_digest', 'history_receipt_digest'): _hash(state[field], field)
        current = CandidatePackage(R(state['selected_package']))
        manifest = TrainingManifest(R(value['training_manifest']))
        learned = TrainingManifest(R(current.record.data()['training_manifest']))
        if not set(learned.identities()) <= set(manifest.identities()):
            raise ContractError('selected component omitted learned TRAIN exposure')
        if package is not None and (package != current or selection != state['selection_digest'] or provenance != manifest):
            raise ContractError('atomic components disagree on selection, package or TRAIN provenance')
        package, selection, provenance = current, state['selection_digest'], manifest
    return bundle, recipe, package, selection, provenance


@dataclass(frozen=True)
class SelectedBundleValidationPanel(FrozenPanel):
    """A fixed paired final acceptance, deliberately outside CombinationPanel."""
    def __post_init__(self):
        object.__setattr__(self, 'legal_arm_grids', MappingProxyType(dict(self.legal_arm_grids)))
        object.__setattr__(self, 'cells', tuple(self.cells))
        object.__setattr__(self, 'scope_ids', tuple(self.scope_ids))
        if (self.stage != 'V_final' or self.domain != 'validation' or len(self.scope_ids) != 1
                or set(self.legal_arm_grids) != set(self.scope_ids)
                or self.required_benchmarks != ('discoverybench', 'blade')
                or type(self.acceptance_criteria) is not FrozenRecord):
            raise ContractError('fixed final validation scope and primary pair required')
        self.combinations.__post_init__()
        _hash(self.split_digest, 'split'); _hash(self.candidate_digest, 'candidate')
        design = self.design.data()
        if (set(design) != {'schema', 'scope', 'bundles', 'train_freeze', 'execution'}
                or design['schema'] != 'selected-bundle-validation-design-v1'
                or design['scope'] not in SCOPES or self.scope_ids != (SCOPES[design['scope']],)
                or set(design['bundles']) != {'baseline', 'candidate'}):
            raise ContractError('C4/C5 acceptance cannot promote other scopes or select additional arms')
        specs = {role: bundle_spec(JointDeploymentBundle(R(value))) for role, value in design['bundles'].items()}
        if (specs['baseline'][1]['procedure'] != 'baseline_b0'
                or specs['candidate'][1]['procedure'] == 'baseline_b0'
                or specs['candidate'][0].digest != self.candidate_digest
                or specs['baseline'][0].digest == self.candidate_digest
                or any(specs['baseline'][0].record.data()[k] != specs['candidate'][0].record.data()[k]
                       for k in ('baseline_digest', 'p0_digest'))):
            raise ContractError('exact unchanged baseline and selected candidate required')
        execution = design['execution']
        if (set(execution) != {'objective', 'image', 'model_config', 'runtime_sources', 'source_authorities'}
                or not isinstance(execution['objective'], dict) or not execution['objective']
                or not isinstance(execution['model_config'], dict) or not execution['model_config']
                or not isinstance(execution['runtime_sources'], dict) or not execution['runtime_sources']
                or '@sha256:' not in execution['image']):
            raise ContractError('frozen execution inputs, model and implementation pins required')
        for value in execution['runtime_sources'].values(): _hash(value, 'runtime source')
        groups = {}; keys = set()
        if not self.cells or any(type(c) is not PanelCell for c in self.cells):
            raise ContractError('exact fixed paired cells required')
        for cell in self.cells:
            if (cell.coverage_id != self.scope_ids[0] or cell.identity.domain != 'validation'
                    or cell.identity.split_id != self.split_digest or cell.variant != 'fixed_acceptance'
                    or cell.arm_id not in specs or cell.key in keys):
                raise ContractError('validation cell scope, domain, variant or multiplicity drift')
            bundle, recipe, *_ = specs[cell.arm_id]
            arm = default_compatibility(bundle.record.data()['baseline_digest']).arm(
                [m for m, level in recipe['target_levels'].items() if level])
            if cell.package_digest != bundle.digest or cell.runtime_arm != arm:
                raise ContractError('cell must execute its exact frozen component bundle')
            keys.add(cell.key); groups.setdefault(cell.task_panel_key, []).append(cell)
        if ({c.identity.benchmark for c in self.cells} != set(self.required_benchmarks)
                or len({c.scorer_digest for c in self.cells}) != 1):
            raise ContractError('primary pair or scorer coverage differs')
        for rows in groups.values():
            if (len(rows) != 2 or {c.arm_id for c in rows} != {'baseline', 'candidate'}
                    or len({(c.identity, c.task_digest, c.scenario_digest) for c in rows}) != 1):
                raise ContractError('every held-out task requires exactly the same frozen pair')

    @property
    def design(self): return self.legal_arm_grids[self.scope_ids[0]]

    def spec(self, role):
        return bundle_spec(JointDeploymentBundle(R(self.design.data()['bundles'][role])))

    def verify_freeze(self, authority_keys):
        self.__post_init__()
        design = self.design.data()
        body = verify_signed(R(design['train_freeze']), authority_keys, schema='selected-bundle-train-freeze-v1')
        required = {'schema', 'authority', 'domain', 'status', 'scope', 'bundle_digests', 'selection_digest',
                    'training_receipts_digest', 'selection_rule_digest', 'protocol_digest', 'selected_snapshot_digest',
                    'execution_digest'}
        if (set(body) != required or body['domain'] != 'train' or body['status'] != 'frozen'
                or body['scope'] != design['scope']
                or body['bundle_digests'] != {role: self.spec(role)[0].digest for role in ('baseline', 'candidate')}
                or body['selection_digest'] != self.spec('candidate')[3]
                or body['execution_digest'] != R(design['execution']).content_hash):
            raise ContractError('selected pair lacks its exact independently signed TRAIN freeze')
        for field in ('selection_digest', 'training_receipts_digest', 'selection_rule_digest',
                      'protocol_digest', 'selected_snapshot_digest'): _hash(body[field], field)
        if design['execution']['runtime_sources'] != runtime_sources():
            raise ContractError('fixed validation implementation differs from frozen sources')
        for role in ('baseline', 'candidate'):
            self.spec(role)[0].verify_sources({name: ROOT for name in MODULES})
        return R(body)


def serialize_selected_panel(panel):
    from evaluation.modular.scorer_process import serialize_frozen_panel
    if type(panel) is not SelectedBundleValidationPanel:
        raise ContractError('exact fixed selected validation panel required')
    value = serialize_frozen_panel(panel)
    value['schema'] = 'selected-bundle-validation-panel-v1'
    return value


def parse_selected_panel(value):
    from research_loop.modular.contracts import DataIdentity
    from research_loop.modular.panel_receipts import CombinationObligations
    if (not isinstance(value, dict) or set(value) != {'schema', 'panel_digest', 'panel'}
            or value['schema'] != 'selected-bundle-validation-panel-v1'):
        raise ContractError('exact selected panel serialization required')
    body = dict(value['panel']); combo = body.pop('combinations')
    body['cells'] = tuple(PanelCell(**{**row, 'identity': DataIdentity.parse(row['identity']),
        'runtime_arm': R(row['runtime_arm'])}) for row in body['cells'])
    body['legal_arm_grids'] = {k: R(v) for k, v in body['legal_arm_grids'].items()}
    body['acceptance_criteria'] = R(body['acceptance_criteria'])
    body['required_benchmarks'] = tuple(body['required_benchmarks'])
    body['combinations'] = CombinationObligations(tuple(tuple(v) for v in combo['pairs']),
        tuple(tuple(v) for v in combo['triples']), tuple(combo['full_arm']), tuple(combo['leave_one_out']))
    panel = SelectedBundleValidationPanel(**body)
    if serialize_selected_panel(panel) != value:
        raise ContractError('selected panel serialization differs from canonical subject')
    return panel
