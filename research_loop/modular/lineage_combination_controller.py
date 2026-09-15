"""Closed custody/compiler/controller for all four frozen lineage designs."""
from research_loop.modular.ordinary_provider import (family_service_preflight, model_root, allocation_fields, provider_usage, provider_terminal, unused_main_opportunities, provider_scope, bind_runtime_originals)
from research_loop.modular.ordinary_provider import final_provider_gate, final_score_fields, unavailable_provider_contrast, final_usage, final_unused
from research_loop.modular.phase_provider import PhaseProviderSession
from dataclasses import dataclass
import hashlib
from pathlib import Path

from evaluation.modular.train_io import PublicTrainPacket
from research_loop.modular.combination_train_source import (
    CombinationTrainSource, source_schema_matches, source_item_matches, packet_index,
)
from evaluation.modular.scoring_service import ScorerConfig
from evaluation.modular.lineage_combination_scoring import (LineageCombinationScoringService,
    issue_lineage_score_input, verify_lineage_score)
from research_loop.modular.combination_train_controller import _service_preflight, _usage, _ANALYSIS, _digest, _names
from research_loop.modular.combination_panels import CombinationPanel, CombinationPanelVerifier
from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.contracts import FrozenRecord, DataIdentity
from research_loop.modular.lineage_combination_driver import (DESIGNS, SLOTS, registered_design,
    run_lineage_combination_cell, verify_lineage_combination_cell)
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial, DualMaterialVerifier, check_material_inputs
from research_loop.modular.model_port import _validate_schema, _schema_witness
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.panel_receipts import PanelCell, PanelReceiptVerifier
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.lineage_useful_controls import source_contract_body
from research_loop.modular.train_provider_preflight import (native_envelope, native_source_fields,
    response_schemas, validate_native_declaration)
from research_loop.modular.train_controller import _checked_roots, _write
from research_loop.ontology import ContractError


def _arms(baseline, designs=DESIGNS):
    return {row['arm_digest']: FrozenRecord.from_dict(row['arm']) for name in designs
            for row in registered_design(name, baseline).data()['cells'] if row['status'] == 'executable'}


@dataclass(frozen=True)
class FrozenLineageTrainConfig:
    record: FrozenRecord

    def _contract(self):
        from research_loop.modular.admission_combination_controller import FrozenAdmissionTrainConfig
        from research_loop.modular.admission_combination import DESIGNS as ADMISSION_DESIGNS, FrozenAdmissionMaterial
        if type(self) is FrozenAdmissionTrainConfig:
            return ADMISSION_DESIGNS, FrozenAdmissionMaterial, 'admission-combination-train-config-v1', 12
        if type(self) is not FrozenLineageTrainConfig: raise ContractError('closed train configuration type required')
        return DESIGNS, FrozenLineageMaterial, 'lineage-combination-train-config-v1', 17

    def __post_init__(self):
        if not isinstance(self.record, FrozenRecord): raise ContractError('frozen lineage train configuration required')
        b = self.data()
        designs, material_type, schema, cell_count = self._contract()
        family = 'admission' if schema == 'admission-combination-train-config-v1' else 'lineage'
        native = native_envelope(b, family)
        required = {'schema', 'domain', 'stage', 'item_ids', 'task_bindings', 'baseline_digest', 'packages_by_arm',
            'scorer', 'scorer_handle_bindings', 'acceptance_criteria', 'replicates', 'model', 'effort', 'max_calls',
            'max_tokens', 'schemas', 'allocation', 'image', 'timeout_seconds', 'materials_by_task', 'source_verifier_binding'}
        source_body = b if native else source_contract_body(b, schema)
        schema_ok = (source_schema_matches(source_body, required, schema)
                     if schema == 'admission-combination-train-config-v1' else
                     source_schema_matches(source_body, required, schema, optional=('lineage_reference_binding',)))
        if native:
            from research_loop.modular.lineage_useful_controls import RECIPE
            schema_ok = (native_source_fields(b, required|{'execution_recipe'}, family=family,
                optional=('lineage_reference_binding',) if family=='lineage' else ())
                and b.get('execution_recipe') == RECIPE.data())
        if (not schema_ok or b['domain'] != 'train'
                or not isinstance(b['stage'], str) or not b['stage'].strip() or not _names(b['item_ids'])
                or not _names(b['replicates']) or not _digest(b['baseline_digest'])):
            raise ContractError('closed lineage train scope or source list invalid')
        bindings = b['task_bindings']
        if not isinstance(bindings, dict) or set(bindings) != set(b['item_ids']):
            raise ContractError('exact train identity and CSV bindings required')
        identities, task_digests = [], []
        for item, row in bindings.items():
            if not isinstance(row, dict) or set(row) != {'identity', 'task_digest', 'csv_sha256', 'csv_byte_count'}:
                raise ContractError('source binding fields drift')
            identity = DataIdentity.parse(row['identity']); identity.require_train()
            if (not source_item_matches(b, item, identity) or not _digest(row['task_digest'])
                    or not _digest(row['csv_sha256']) or type(row['csv_byte_count']) is not int or row['csv_byte_count'] < 0):
                raise ContractError('source binding types or identity drift')
            identities.append(identity); task_digests.append(row['task_digest'])
        if {i.benchmark for i in identities} != {'blade', 'discoverybench'} or len({i.split_id for i in identities}) != 1 or len(set(task_digests)) != len(task_digests):
            raise ContractError('both core benchmarks in one train split required')
        if not isinstance(b['materials_by_task'], dict) or set(b['materials_by_task']) != set(task_digests):
            raise ContractError('material must exactly cover every prepared task')
        for row in bindings.values():
            material = material_type(FrozenRecord.from_dict(b['materials_by_task'][row['task_digest']]))
            if (material.data()['identity'] != row['identity'] or material.data()['task_digest'] != row['task_digest']
                    or material.data()['public_artifacts'] != [{'artifact': {'artifact_id': 'public_csv',
                        'sha256': row['csv_sha256'], 'byte_count': row['csv_byte_count']}, 'container_path': '/input/public_csv'}]):
                raise ContractError('controller material must use exact custody CSV source')
        arms = _arms(b['baseline_digest'], designs)
        if not isinstance(b['packages_by_arm'], dict) or set(b['packages_by_arm']) != set(arms):
            raise ContractError('packages must exactly cover all legal arms across the four designs')
        packages = [CandidatePackage(FrozenRecord.from_dict(p)) for p in b['packages_by_arm'].values()]
        if len({p.digest for p in packages}) != 1 or any(set(TrainingManifest(FrozenRecord.from_dict(p.record.data()['training_manifest'])).identities()) != set(identities) for p in packages):
            raise ContractError('all arms need one exact candidate and train history identity set')
        s = b['scorer']
        if not isinstance(s, dict) or ScorerConfig.create(benchmark='core_pair', evaluator_id=s.get('evaluator_id'), version=s.get('version'), rubric_digest=s.get('rubric_digest')).record.data() != s:
            raise ContractError('one frozen core-pair scorer required')
        handles = b['scorer_handle_bindings']
        if not isinstance(handles, dict) or set(handles) != {FrozenRecord.from_dict(i.data()).content_hash for i in identities} or any(not _digest(v) for v in handles.values()):
            raise ContractError('exact independent scorer handle delegation required')
        if 'lineage_reference_binding' in b:
            ref = b['lineage_reference_binding']
            if (not isinstance(ref, dict) or set(ref) != {'manifest_sha256', 'references', 'subjects', 'limits'}
                    or not _digest(ref['manifest_sha256']) or not isinstance(ref['references'], dict)
                    or set(ref['references']) != set(handles) or any(not _digest(v) for v in ref['references'].values())):
                raise ContractError('frozen lineage scorer reference bindings invalid')
            expected_subjects = {FrozenRecord.from_dict(row['identity']).content_hash: {
                'task_digest': row['task_digest'], 'material_digest': FrozenRecord.from_dict(b['materials_by_task'][row['task_digest']]).content_hash}
                for row in bindings.values()}
            limits = ref['limits']
            expected_scorer_model = 'grok-4.6' if native else 'gpt-5.6-luna'
            if (ref['subjects'] != expected_subjects or not isinstance(limits, dict)
                    or set(limits) != {'model', 'effort', 'tokens_per_cell', 'timeout_seconds'}
                    or limits['model'] != expected_scorer_model or limits['effort'] != 'low'
                    or type(limits['tokens_per_cell']) is not int or limits['tokens_per_cell'] < 1
                    or type(limits['timeout_seconds']) is not int or not 1 <= limits['timeout_seconds'] <= 600):
                raise ContractError('lineage scorer subject or per-cell budget drift')
        if not isinstance(b['acceptance_criteria'], dict) or b['acceptance_criteria'].get('contrast_analysis') != _ANALYSIS:
            raise ContractError('registered incomplete-reject contrast criteria required')
        n = len(identities) * len(b['replicates']) * cell_count
        allocation = {'model_slots_per_cell': list(SLOTS), 'docker_attempts_per_cell': 1, 'scorer_calls_per_cell': 1,
            'scorer_call_limit': n, 'scorer_token_accounting': 'transport_not_provided', 'source_calls_per_cell': 2}
        if FrozenRecord.from_dict(b['allocation']) != FrozenRecord.from_dict(allocation):
            raise ContractError('four model, one Docker, two source and one scorer allocations must match')
        if ((not native and (b['model'] != 'gpt-5.6-luna' or b['effort'] != 'low' or type(b['max_calls']) is not int or b['max_calls'] != n*4
                or type(b['max_tokens']) is not int or b['max_tokens'] < 1)) or type(b['timeout_seconds']) is not int
                or not 1 <= b['timeout_seconds'] <= 120 or not isinstance(b['image'], str) or '@sha256:' not in b['image']
                or not _digest(b['image'].rsplit('@sha256:', 1)[1])):
            raise ContractError('bounded matched model and pinned Docker configuration required')
        schemas = response_schemas(b, family=family)
        if not isinstance(schemas, dict) or set(schemas) != set(SLOTS): raise ContractError('exact four shared response schemas required')
        for schema in schemas.values():
            if not isinstance(schema, dict) or schema.get('type') != 'object': raise ContractError('object response schema required')
            _validate_schema(schema, _schema_witness(schema))
        if native:
            validate_native_declaration(b, family=family, schemas=schemas, main_opportunities=n*4)
        source = b['source_verifier_binding']
        if (not isinstance(source, dict) or set(source) != {'authorities', 'cost_limit_per_call'}
                or type(source['cost_limit_per_call']) is not int or source['cost_limit_per_call'] < 1
                or not isinstance(source['authorities'], list) or len(source['authorities']) != 2
                or any(not isinstance(a, dict) or set(a) != {'authority', 'source_group', 'key_digest'}
                    or not isinstance(a['authority'], str) or not a['authority'] or not isinstance(a['source_group'], str)
                    or not a['source_group'] or not _digest(a['key_digest']) for a in source['authorities'])
                or any(len({a[k] for a in source['authorities']}) != 2 for k in ('authority', 'source_group', 'key_digest'))):
            raise ContractError('two frozen source authorities required')

    def data(self): return self.record.data()


@dataclass(frozen=True)
class CompiledLineagePanels:
    panels: tuple
    packets: tuple
    scenarios: dict
    packages: dict
    materials: dict


def compile_lineage_train_panels(config, packets):
    if not isinstance(config, FrozenLineageTrainConfig) or not isinstance(packets, tuple) or any(not isinstance(p, PublicTrainPacket) for p in packets):
        raise ContractError('typed frozen configuration and exported custody packets required')
    b = config.data(); by_item = packet_index(b, packets)
    designs, material_type, _, _ = config._contract()
    if len(by_item) != len(packets) or set(by_item) != set(b['item_ids']): raise ContractError('missing or duplicate exported task')
    for item, packet in by_item.items():
        binding = b['task_bindings'][item]
        if DockerExecutionBroker._has_link_component(packet.csv_path): raise ContractError('source cannot be a link')
        data = packet.csv_path.read_bytes()
        if (packet.task.identity.data() != binding['identity'] or packet.task.content_hash != binding['task_digest']
                or hashlib.sha256(data).hexdigest() != binding['csv_sha256'] or len(data) != binding['csv_byte_count']
                or packet.receipt.data().get('csv_sha256') != binding['csv_sha256']
                or packet.receipt.data().get('packet_hash') != binding['task_digest']):
            raise ContractError('exported task or exact CSV bytes drifted')
    packages = {k: CandidatePackage(FrozenRecord.from_dict(v)) for k,v in b['packages_by_arm'].items()}
    materials = {k: material_type(FrozenRecord.from_dict(v)) for k,v in b['materials_by_task'].items()}
    panels, scenarios = [], {}
    for name in designs:
        design = registered_design(name, b['baseline_digest']); cells = []
        arms = {r['id']: FrozenRecord.from_dict(r['arm']) for r in design.data()['cells'] if r['status'] == 'executable'}
        for item in b['item_ids']:
            packet = by_item[item]
            for replicate in b['replicates']:
                scenario = FrozenRecord.from_dict({'schema': 'lineage-combination-scenario-v1', 'obligation_id': name,
                    'design_digest': design.content_hash, 'task_digest': packet.task.content_hash, 'replicate': replicate,
                    'material_digest': materials[packet.task.content_hash].record.content_hash,
                    **({'schema':'lineage-combination-scenario-v2', 'execution_recipe':b['execution_recipe']}
                       if 'execution_recipe' in b else {})})
                for arm_id, arm in arms.items():
                    cell = PanelCell(name, packet.task.identity, replicate, 'combination', arm_id, arm,
                        packet.task.content_hash, scenario.content_hash, packages[arm.content_hash].digest,
                        FrozenRecord.from_dict(b['scorer']).content_hash)
                    cells.append(cell); scenarios[cell.key] = scenario
        panel = CombinationPanel(b['stage'], 'train', packets[0].task.identity.split_id, name, 'interaction_on_scale', design,
            FrozenRecord.from_dict({'schema': 'combination-package-bundle-v1', 'packages': {a.content_hash: packages[a.content_hash].record.data() for a in arms.values()}}),
            FrozenRecord.from_dict(b['acceptance_criteria']), tuple(cells))
        panels.append(panel)
    return CompiledLineagePanels(tuple(panels), packets, scenarios, packages, materials)


@dataclass(frozen=True)
class LineageTrainRun:
    compiled: CompiledLineagePanels
    results: tuple
    scores: tuple
    attempts: tuple
    contrasts: tuple
    receipt: FrozenRecord


def _v3_admission_qualification_semantics(config, cell, material, qualifier, path):
    """Return only the signed qualification fields the admission transition consumes.

    A source receipt cannot be compared byte-for-byte across matched arms: its
    request binds a distinct cell and its signature/call bookkeeping is also
    intentionally distinct.  This projection keeps the before/after
    assessments separate and excludes that incidental receipt metadata.
    """
    from research_loop.modular.admission_combination_controller import FrozenAdmissionTrainConfig
    if type(config) is not FrozenAdmissionTrainConfig or 'execution_recipe' not in config.data():
        return None
    return admission_qualification_semantics(cell, material, qualifier, path, config.data()['source_verifier_binding'])


def admission_qualification_semantics(cell, material, qualifier, path, source_binding):
    """Project the exact subject-bound semantic fields consumed by admission."""
    binding = FrozenRecord.from_dict({'cell_digest': FrozenRecord.from_dict(cell.data()).content_hash,
                                      'scenario_digest': cell.scenario_digest})
    assessments = qualifier.assessments(material, path, cell_binding=binding)
    consumed = {}
    for phase in ('before', 'after'):
        consumed[phase] = {}
        for key in material.subjects()[phase]:
            value = assessments[phase][key]
            consumed[phase][key] = {field: value[field] for field in
                                    ('subject_digest', 'state', 'outcome', 'execution_success', 'audit')}
    return FrozenRecord.from_dict({'schema': 'v3-admission-qualification-semantics-v1',
        'task_digest': cell.task_digest, 'material_digest': material.record.content_hash,
        'source_verifier_binding': source_binding, 'assessments': consumed})


def _v3_admission_qualification_drift(config, panel, rows):
    """Return compact, non-sensitive evidence when comparable v3 arms differ."""
    from research_loop.modular.admission_combination_controller import FrozenAdmissionTrainConfig
    if type(config) is not FrozenAdmissionTrainConfig or 'execution_recipe' not in config.data():
        return None
    return admission_qualification_drift(panel, rows)


def admission_qualification_drift(panel, rows):
    """Compare completed matched cells; incomplete outcomes stay incomplete."""
    expected = {FrozenRecord.from_dict(cell.data()).content_hash for cell in panel.cells}
    comparable = [row for row in rows if FrozenRecord.from_dict(row['cell']).content_hash in expected]
    groups = {}
    for row in comparable:
        cell = row['cell']; key = (cell['task_digest'], cell['replicate'])
        groups.setdefault(key, []).append(row)
    drift = []
    for (task_digest, replicate), group in groups.items():
        if len(group) != len([cell for cell in panel.cells if cell.task_digest == task_digest and cell.replicate == replicate]):
            continue  # Existing incomplete-cell handling determines this outcome.
        if any(row.get('status') != 'succeeded' for row in group):
            continue  # Preserve incomplete/unknown source failure handling.
        by_arm = {row['cell']['arm_id']: row.get('qualification_semantics_digest') for row in group}
        if None in by_arm.values() or len(set(by_arm.values())) != 1:
            drift.append({'task_digest': task_digest, 'replicate': replicate, 'arm_semantics': by_arm})
    return drift or None


def run_lineage_train_panels(config, *, custody, snapshot_root, export_root, run_root, model, audit_verifier,
        source_verifier, execution_authority, scoring_service, scorer_authority_keys, prospective_exporter=None):
    from evaluation.modular.lineage_scorer_process import LineageScorerProcessPool
    from research_loop.modular.admission_combination_controller import FrozenAdmissionTrainConfig
    from research_loop.modular.admission_combination import AdmissionMaterialVerifier, issue_admission_score_input, DESIGNS as ADMISSION_DESIGNS
    from evaluation.modular.scorer_process import CombinationScorerProcessClient
    from evaluation.modular.combination_scoring import verify_combination_adapted_receipt
    admission = type(config) is FrozenAdmissionTrainConfig
    if admission:
        if (type(source_verifier) is not AdmissionMaterialVerifier or not isinstance(scoring_service, dict)
                or set(scoring_service) != set(ADMISSION_DESIGNS)
                or any(type(s) is not CombinationScorerProcessClient for s in scoring_service.values())):
            raise ContractError('admission controller requires dual qualifiers and three independent scorer processes')
        if (not hasattr(execution_authority, 'key') or not isinstance(scorer_authority_keys, dict)
                or any(a.authority.key in {execution_authority.key, *scorer_authority_keys.values()}
                       for a in source_verifier.authorities)):
            raise ContractError('source, execution and scorer authority roles require independent keys')
    if (not isinstance(config, FrozenLineageTrainConfig)
            or not isinstance(audit_verifier, AuditVerifier) or not isinstance(source_verifier, DualMaterialVerifier)
            or (not admission and not isinstance(scoring_service, (LineageCombinationScoringService, LineageScorerProcessPool)))
            or source_verifier.binding().data() != config.data()['source_verifier_binding']):
        raise ContractError('closed lineage train dependencies or source authorities drifted')
    if isinstance(scoring_service, LineageScorerProcessPool):
        if config.data().get('lineage_reference_binding') != scoring_service.reference_binding:
            raise ContractError('lineage process references not frozen in train configuration')
    elif 'lineage_reference_binding' in config.data():
        raise ContractError('reference-bound lineage configuration requires the process pool')
    for service in scoring_service.values() if admission else (scoring_service,):
        family_service_preflight(config, model, service, execution_authority, scorer_authority_keys, family=('admission' if admission else 'lineage'))
    score_verifier = verify_combination_adapted_receipt if admission else verify_lineage_score
    source_issuer = issue_admission_score_input if admission else issue_lineage_score_input
    def reference_options(cell):
        return {} if admission else {'expected_reference_digest': config.data().get('lineage_reference_binding', {}).get('references', {}).get(
            FrozenRecord.from_dict(cell.identity.data()).content_hash)}
    native = native_envelope(config.data(), ('admission' if admission else 'lineage'))
    headless_lineage = (not admission and native and isinstance(scoring_service, LineageScorerProcessPool)
                        and hasattr(scoring_service, 'evaluator_usage_by_obligation')
                        and hasattr(scoring_service, 'evaluator_providers_by_obligation'))
    if not admission and isinstance(scoring_service, LineageScorerProcessPool) and hasattr(scoring_service, 'evaluator_usage_by_obligation') and not native:
        raise ContractError('headless lineage evaluator requires the native v4 train envelope')
    snapshot, exported, root, _ = _checked_roots(snapshot_root, export_root, run_root, model_root(model, native=native))
    if root.exists() or exported.exists(): raise ContractError('closed controller requires unused roots and no retry')
    b = config.data()
    source = CombinationTrainSource(b, custody=custody, prospective_exporter=prospective_exporter,
                                  snapshot=snapshot, exported=exported)
    root.mkdir(parents=True)
    provider_session = PhaseProviderSession(model, root/'provider-scopes.json') if native else None
    journal = {'schema': ('lineage-train-attempt-v2' if native else 'lineage-train-attempt-v1'), 'config_digest': config.record.content_hash, 'status': 'exporting',
        'allocation': b['allocation'], **allocation_fields(b, native=native), 'cells': [], 'actual_scorer_calls': 0}
    def persist():
        journal['actual_model_usage'] = provider_usage(provider_session, model); _write(root/'controller-attempt.json', journal)
    persist()
    try:
        packets = source.export()
        journal['packet_receipts'] = [p.receipt.data() for p in packets]; persist()
        compiled = compile_lineage_train_panels(config, packets)
        if isinstance(scoring_service, LineageScorerProcessPool) and any(
                scoring_service.clients[p.obligation_id].panel != p for p in compiled.panels):
            raise ContractError('lineage process panel differs from actual compiled panel')
        if admission and any(scoring_service[p.obligation_id].panel != p for p in compiled.panels):
            raise ContractError('scorer process panel differs from actual custody compiler')
        broker = DockerExecutionBroker([exported, root])
        by_task = {p.task.content_hash: p for p in packets}
        # Check all deterministic materials and bytes before any external authority/model call.
        from research_loop.modular.lineage_combination_driver import _transition
        from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
        from research_loop.modular.modules.context import ContextCache
        for panel in compiled.panels:
            for cell in panel.cells:
                material = compiled.materials[cell.task_digest]; task = by_task[cell.task_digest].task
                check_material_inputs(material, task, broker, {'public_csv': by_task[cell.task_digest].csv_path})
                if not admission:
                    e = EvidenceLedger(task.identity); _transition(e, ClaimLedger(e), ContextCache(), material, set(cell.runtime_arm.data()['enabled']))
        journal.update(status='executing', panels=[{'digest': p.digest, 'design': p.design.data(), 'cells': [c.data() for c in p.cells]} for p in compiled.panels],
            packet_receipts=[p.receipt.data() for p in packets],
            cells=[{'cell': c.data(), 'status': 'not_started', 'phase': 'planned', 'scorer_calls': 0} for p in compiled.panels for c in p.cells])
        persist()
    except Exception as exc:
        journal.update(status='blocked_before_execution', error_type=type(exc).__name__); persist(); raise
    results, scores, score_inputs, runtime_by_panel = [], [], {}, {}
    for index, (panel, cell) in enumerate((p,c) for p in compiled.panels for c in p.cells):
        service = scoring_service[panel.obligation_id] if admission else scoring_service
        row = journal['cells'][index]; result = None
        row.update(status='running', phase='material_verification', model_usage_before=provider_usage(provider_session, model)); persist()
        cell_root = root/'cells'/FrozenRecord.from_dict(cell.data()).content_hash
        try:
            if provider_terminal(provider_session, model):
                row.update(status='blocked', phase='model_allocation', reason='prior_usage_incomplete'); continue
            packet = by_task[cell.task_digest]
            args = dict(panel=panel, task=packet.task, scenario=compiled.scenarios[cell.key],
                package=compiled.packages[cell.runtime_arm.content_hash], material=compiled.materials[cell.task_digest],
                source_verifier=source_verifier, public_inputs={'public_csv': packet.csv_path}, broker=broker)
            with provider_scope(provider_session, model, cell) as scoped_model:
                result = run_lineage_combination_cell(cell=cell, **args, objective=FrozenRecord.from_dict({'panel_digest': panel.digest}),
                    sidecar=cell_root, image=b['image'], model=scoped_model, audit_verifier=audit_verifier, timeout_seconds=b['timeout_seconds'])
            row.update(phase='source_verification', runtime=PanelReceiptVerifier._runtime_data(result.runtime)); persist()
            if result.cell != cell or result.runtime.cell_key != cell.key: raise ContractError('foreign executor cell')
            verified = verify_lineage_combination_cell(result, **args)
            row['verification'] = verified.data(); runtime_by_panel.setdefault(panel.digest, []).append(result.runtime)
            semantics = _v3_admission_qualification_semantics(config, cell, compiled.materials[cell.task_digest],
                source_verifier, cell_root/'source-verification.json')
            if semantics is not None:
                row['qualification_semantics_digest'] = semantics.content_hash
            if result.runtime.status != 'succeeded':
                row.update(status='failed', phase='execution', reason='original_execution_failure'); continue
            source = source_issuer(authority=execution_authority, result=result, **args); score_inputs[cell.key] = source
            if native:
                row['provider_seal_digest'] = bind_runtime_originals(provider_session, cell, result.runtime, cell_root/'provider-seal.json')
            row.update(phase='scoring', scorer_calls=1, score_input=source.data()); journal['actual_scorer_calls'] += 1; persist()
            score = (service.score_combination if admission else service.score_lineage)(panel=panel, cell=cell, score_input=source)
            row.update(phase='score_verification', scorer_receipt=score.receipt.data())
            score_verifier(score, authority_keys=scorer_authority_keys, config=service.config, panel=panel,
                cell=cell, score_input=source, execution_authority_keys={execution_authority.authority_id: execution_authority.key}, **reference_options(cell))
            scores.append(score)
            if native:
                row['post_score_provider_seal_digest'] = bind_runtime_originals(provider_session, cell, result.runtime, cell_root/'post-score-provider-seal.json')
            row.update(status='succeeded', phase='verified')
        except Exception as exc:
            row.update(status='failed', error_type=type(exc).__name__)
        finally:
            if isinstance(scoring_service, LineageScorerProcessPool) and row['scorer_calls']:
                row['independent_scorer_usage'] = scoring_service.clients[panel.obligation_id].usage()
            row['model_usage_after'] = provider_usage(provider_session, model)
            source_path = cell_root/'source-verification.json'
            if source_path.is_file():
                import json
                row['source_verification'] = json.loads(source_path.read_text(encoding='utf-8'))
                row['source_sha256'] = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if result and result.solver and result.solver.execution: row['execution_receipt'] = result.solver.execution.data()
            row['docker_attempts'] = (sum(FrozenRecord(line).data()['stage'] == 'execution_request'
                for line in result.runtime.trace_path.read_text(encoding='utf-8').splitlines()) if result else 0)
            results.append(result); persist()
    final_gate = final_provider_gate(provider_session, root/'final-provider-ledger.json')
    lineage_evaluator_gate = None
    if headless_lineage:
        # Journal order is the controller's actual submission order.  Do not
        # derive closure input from the cross-panel score collection.
        closures = []
        for panel in compiled.panels:
            expected_cells = {FrozenRecord.from_dict(cell.data()).content_hash for cell in panel.cells}
            receipt_digests = [FrozenRecord.from_dict(row['scorer_receipt']).content_hash
                for row in journal['cells'] if FrozenRecord.from_dict(row['cell']).content_hash in expected_cells
                and row.get('status') == 'succeeded' and 'scorer_receipt' in row]
            client = scoring_service.clients[panel.obligation_id]
            declaration = scoring_service.evaluator_usage_by_obligation[panel.obligation_id]
            provider = scoring_service.evaluator_providers_by_obligation[panel.obligation_id]
            entry = {'obligation_id': panel.obligation_id, 'panel_digest': panel.digest,
                     'receipt_digests': receipt_digests, 'evaluator_usage_declaration': declaration,
                     'evaluator_provider': provider,
                     'title_and_all_opportunity_settlement': 'unknown'}
            try:
                closure = client.finalize_lineage(nonce=panel.digest, receipt_digests=receipt_digests)
                entry.update(status='eligible', closure=closure.data(), closure_digest=closure.content_hash,
                             native_MAIN=closure.data().get('known_main_tokens'))
            except Exception as exc:
                entry.update(status='inconclusive', reason='closure_unavailable_or_rejected',
                             error_type=type(exc).__name__, native_MAIN='unknown')
            closures.append(entry)
        lineage_evaluator_gate = {'schema': 'lineage-evaluator-final-gate-v1',
            'status': 'eligible' if all(row['status'] == 'eligible' for row in closures) else 'inconclusive',
            'accounting_scope': 'native_MAIN', 'title_and_all_opportunity_settlement': 'unknown',
            'panels': closures}
        journal['lineage_evaluator_final_gate'] = lineage_evaluator_gate
        persist()
    contrasts = []
    for panel in compiled.panels:
        if native and not final_gate.data()['provider_evidence_eligible']:
            contrasts.append(unavailable_provider_contrast(panel, final_gate)); continue
        if headless_lineage and lineage_evaluator_gate['status'] != 'eligible':
            contrasts.append(FrozenRecord.from_dict({'schema': 'lineage-inconclusive-contrast-v1',
                'panel_digest': panel.digest, 'status': 'inconclusive',
                'reason': 'lineage_evaluator_final_provenance_unavailable', 'scientific_status': 'not_measured'})); continue
        service = scoring_service[panel.obligation_id] if admission else scoring_service
        def verify_score(score, cell, owner):
            score_verifier(score, authority_keys=scorer_authority_keys, config=service.config, panel=owner,
                cell=cell, score_input=score_inputs[cell.key], execution_authority_keys={execution_authority.authority_id: execution_authority.key}, **reference_options(cell))
        drift = _v3_admission_qualification_drift(config, panel, journal['cells'])
        if drift is not None:
            contrast = FrozenRecord.from_dict({'schema': 'lineage-inconclusive-contrast-v1', 'panel_digest': panel.digest,
                'status': 'inconclusive', 'reason': 'v3_admission_qualification_semantic_drift',
                'qualification_drift': drift, 'scientific_status': 'not_measured'})
        else:
            try:
                contrast = estimate_grouped_contrast(panel, runtime=runtime_by_panel.get(panel.digest, []),
                    scorer_receipts=[s for s in scores if s.cell_key in {c.key for c in panel.cells}],
                    verifier=CombinationPanelVerifier(scorer_verifier=verify_score))
            except Exception as exc:
                contrast = FrozenRecord.from_dict({'schema': 'lineage-inconclusive-contrast-v1', 'panel_digest': panel.digest,
                    'status': 'inconclusive', 'reason': 'incomplete_or_failed_cell', 'error_type': type(exc).__name__})
        contrasts.append(contrast)
    if native:
        final_gate = final_provider_gate(provider_session, root/'report-provider-ledger.json')
        if not final_gate.data()['provider_evidence_eligible']:
            journal['historical_contrasts_before_failed_final_gate'] = [c.data() for c in contrasts]
            contrasts = [unavailable_provider_contrast(panel, final_gate) for panel in compiled.panels]
    receipt = FrozenRecord.from_dict({'schema': ('lineage-train-receipt-v2' if native else 'lineage-train-receipt-v1'), 'config_digest': config.record.content_hash,
        'expected_cells': len(journal['cells']), 'observed_cells': len(results), 'scored_cells': len(scores), **final_score_fields(final_gate, scores),
        'failed_cells': sum(r['status']=='failed' for r in journal['cells']), 'blocked_cells': sum(r['status']=='blocked' for r in journal['cells']),
        'allocation': b['allocation'], 'actual_model_usage': final_usage(final_gate, model), 'actual_scorer_calls': journal['actual_scorer_calls'],
        'actual_docker_attempts': sum(r['docker_attempts'] for r in journal['cells']),
        'unused_model_opportunities': final_unused(final_gate, model, b),
        'unused_docker_opportunities': len(results) - sum(r['docker_attempts'] for r in journal['cells']),
        'scorer_usage_unknown': journal['actual_scorer_calls'] > 0,
        'source_calls': sum(len(r.get('source_verification', {}).get('calls', [])) for r in journal['cells']),
        **({'lineage_evaluator_final_gate': lineage_evaluator_gate} if lineage_evaluator_gate is not None else {}),
        'contrasts': [c.data() for c in contrasts], 'pruned_cells': [], 'scientific_effectiveness_proven': False, 'validation_opened': False,
        'status': 'complete_train_engineering' if len(scores)==len(results)
            and (lineage_evaluator_gate is None or lineage_evaluator_gate['status'] == 'eligible')
            and all(c.data()['status'] in {'estimated', 'not_identifiable'} for c in contrasts) else 'inconclusive'})
    _write(root/'controller-receipt.json', receipt.data()); journal['status'] = receipt.data()['status']; journal.update(actual_model_usage=receipt.data()['actual_model_usage']); _write(root/'controller-attempt.json',journal)
    return LineageTrainRun(compiled, tuple(results), tuple(scores), tuple(FrozenRecord.from_dict(r) for r in journal['cells']), tuple(contrasts), receipt)
