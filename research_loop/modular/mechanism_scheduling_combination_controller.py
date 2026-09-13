"""Closed prospective TRAIN controller for the three mechanism/scheduling designs."""
from dataclasses import dataclass
import hashlib
from pathlib import Path

from evaluation.modular.train_io import PublicTrainPacket
from research_loop.modular.combination_train_source import (
    CombinationTrainSource, source_schema_matches, source_item_matches, packet_index,
)
from evaluation.modular.scoring_service import ScorerConfig
from evaluation.modular.mechanism_scheduling_scoring import issue_mechanism_scheduling_score_input
from evaluation.modular.combination_scoring import verify_combination_adapted_receipt
from evaluation.modular.scorer_process import CombinationScorerProcessClient
from evaluation.modular.scoring_service import FrozenBenchmarkRubricEndpoint
from research_loop.modular.combination_train_controller import _service_preflight, _usage, _ANALYSIS, _digest, _names
from research_loop.modular.combination_panels import CombinationPanel, CombinationPanelVerifier
from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.contracts import FrozenRecord, DataIdentity
from research_loop.modular.mechanism_scheduling_combination_driver import (DESIGNS, SLOTS, KINDS, recipe, registered_design,
    run_mechanism_scheduling_cell, verify_mechanism_scheduling_cell, FrozenMechanismSchedulingMaterial)
from research_loop.modular.lineage_combination_material import DualMaterialVerifier
from research_loop.modular.exploration_scheduler_combination import check_inputs
from research_loop.modular.retrieval_review_combination_driver import check_material as check_retrieval
from research_loop.modular.model_port import _validate_schema, _schema_witness
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.panel_receipts import PanelCell, PanelReceiptVerifier
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import _checked_roots, _write
from research_loop.ontology import ContractError


def _arms(baseline, designs=DESIGNS):
    return {row['arm_digest']: FrozenRecord.from_dict(row['arm']) for name in designs
            for row in registered_design(name, baseline).data()['cells'] if row['status'] == 'executable'}


def _validate_source_binding(source):
    if (not isinstance(source, dict) or set(source) != {'authorities', 'cost_limit_per_call'}
            or type(source['cost_limit_per_call']) is not int or source['cost_limit_per_call'] < 1
            or not isinstance(source['authorities'], list) or len(source['authorities']) != 2
            or any(not isinstance(a, dict) or set(a) != {'authority', 'source_group', 'key_digest'}
                or not isinstance(a['authority'], str) or not a['authority']
                or not isinstance(a['source_group'], str) or not a['source_group']
                or not _digest(a['key_digest']) for a in source['authorities'])
            or any(len({a[k] for a in source['authorities']}) != 2
                   for k in ('authority', 'source_group', 'key_digest'))):
        raise ContractError('two frozen independent source authority bindings required')


@dataclass(frozen=True)
class FrozenMechanismSchedulingTrainConfig:
    record: FrozenRecord

    def __post_init__(self):
        if not isinstance(self.record, FrozenRecord): raise ContractError('frozen mechanism scheduling train configuration required')
        b = self.data()
        designs = DESIGNS
        schema = 'mechanism-scheduling-combination-train-config-v1'
        required = {'schema', 'domain', 'stage', 'item_ids', 'task_bindings', 'baseline_digest', 'packages_by_arm',
            'scorer', 'scorer_handle_bindings', 'acceptance_criteria', 'replicates', 'model', 'effort', 'max_calls',
            'max_tokens', 'schemas', 'allocation', 'image', 'timeout_seconds', 'materials_by_pair', 'source_verifier_bindings', 'objective'}
        if (type(self) is not FrozenMechanismSchedulingTrainConfig
                or not source_schema_matches(b, required, schema)
                or b.get('export_mode') != 'primary_prospective' or b['domain'] != 'train'
                or not isinstance(b['stage'], str) or not b['stage'].strip()
                or not _names(b['item_ids']) or len(b['item_ids']) != 2
                or not _names(b['replicates']) or len(b['replicates']) != 1 or not _digest(b['baseline_digest'])):
            raise ContractError('exact primary prospective TRAIN source, two tasks and one replicate required')
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
        materials = b['materials_by_pair']
        if not isinstance(materials, dict) or set(materials) != set(DESIGNS):
            raise ContractError('materials must bind the exact three mechanism scheduling pairs')
        budgets = set()
        for pair, entries in materials.items():
            if not isinstance(entries, dict) or set(entries) != set(task_digests):
                raise ContractError('pair materials must cover the exact tasks')
            for row in bindings.values():
                material = FrozenMechanismSchedulingMaterial(FrozenRecord.from_dict(entries[row['task_digest']]))
                if material.data()['kind'] != KINDS[pair]:
                    raise ContractError('pair requires its exact composite mechanism type')
                m = material.scheduling().data(); budgets.add(m['context_budget_bytes'])
                if (m['identity'] != row['identity'] or m['task_digest'] != row['task_digest']
                        or m['public_artifacts'] != [{'artifact': {'artifact_id': 'public_csv',
                            'sha256': row['csv_sha256'], 'byte_count': row['csv_byte_count']}, 'container_path': '/input/public_csv'}]):
                    raise ContractError('pair material must bind the exact custody CSV and task')
        if len(budgets) != 1:
            raise ContractError('all pairs and cells require equal context budgets')
        arms = _arms(b['baseline_digest'], designs)
        if not isinstance(b['packages_by_arm'], dict) or set(b['packages_by_arm']) != set(arms):
            raise ContractError('packages must exactly cover all legal arms across the three designs')
        packages = [CandidatePackage(FrozenRecord.from_dict(p)) for p in b['packages_by_arm'].values()]
        if len({p.digest for p in packages}) != 1 or any(set(TrainingManifest(FrozenRecord.from_dict(p.record.data()['training_manifest'])).identities()) != set(identities) for p in packages):
            raise ContractError('all arms need one exact candidate and train history identity set')
        s = b['scorer']
        if not isinstance(s, dict) or ScorerConfig.create(benchmark='core_pair', evaluator_id=s.get('evaluator_id'), version=s.get('version'), rubric_digest=s.get('rubric_digest')).record.data() != s:
            raise ContractError('one frozen core-pair scorer required')
        handles = b['scorer_handle_bindings']
        if not isinstance(handles, dict) or set(handles) != {FrozenRecord.from_dict(i.data()).content_hash for i in identities} or any(not _digest(v) for v in handles.values()):
            raise ContractError('exact independent scorer handle delegation required')
        if not isinstance(b['acceptance_criteria'], dict) or b['acceptance_criteria'].get('contrast_analysis') != _ANALYSIS:
            raise ContractError('registered incomplete-reject contrast criteria required')
        if s['rubric_digest'] != FrozenBenchmarkRubricEndpoint.rubric_digest():
            raise ContractError('exact frozen primary scorer rubric required')
        n = 24
        allocation = {'model_slots_by_pair': {p:list(v) for p,v in SLOTS.items()}, 'retrieval_calls_by_pair': {p:3 if KINDS[p]=='retrieval' else 0 for p in DESIGNS}, 'docker_attempts_per_cell': 3,
            'auxiliary_docker_attempts_per_cell': 2, 'solver_docker_attempts_per_cell': 1,
            'scorer_calls_per_cell': 1, 'scorer_call_limit': n, 'scorer_token_accounting': 'transport_not_provided',
            'source_calls_per_cell': 2, 'phase_cost_units_per_cell': 2, 'phase_job_limit': 2,
            'phase_policy': 'fifo', 'phase_max_concurrency': 2, 'context_budget_bytes': next(iter(budgets))}
        if FrozenRecord.from_dict(b['allocation']) != FrozenRecord.from_dict(allocation):
            raise ContractError('pair-specific model, three Docker, two source, one scorer and matched FIFO phase allocations required')
        if (b['model'] != 'gpt-5.6-luna' or b['effort'] != 'low' or type(b['max_calls']) is not int or b['max_calls'] != 8*sum(map(len,SLOTS.values()))
                or type(b['max_tokens']) is not int or b['max_tokens'] < 1 or type(b['timeout_seconds']) is not int
                or not 1 <= b['timeout_seconds'] <= 120 or not isinstance(b['image'], str) or '@sha256:' not in b['image']
                or not _digest(b['image'].rsplit('@sha256:', 1)[1])):
            raise ContractError('bounded matched model and pinned Docker configuration required')
        schemas = b['schemas']
        if not isinstance(schemas, dict) or set(schemas) != {v for slots in SLOTS.values() for v in slots}: raise ContractError('exact shared response schemas required')
        for schema in schemas.values():
            if not isinstance(schema, dict) or schema.get('type') != 'object': raise ContractError('object response schema required')
            _validate_schema(schema, _schema_witness(schema))
        if not isinstance(b['objective'], dict) or not b['objective']:
            raise ContractError('frozen nonempty public objective required')
        bindings = b['source_verifier_bindings']
        if not isinstance(bindings, dict) or set(bindings) != set(DESIGNS):
            raise ContractError('source verifiers must cover the exact pairs')
        for source in bindings.values():
            _validate_source_binding(source)
        if len({s['cost_limit_per_call'] for s in bindings.values()}) != 1:
            raise ContractError('equal source opportunity cost caps required')

    def data(self): return self.record.data()


@dataclass(frozen=True)
class CompiledMechanismSchedulingPanels:
    panels: tuple
    packets: tuple
    scenarios: dict
    packages: dict
    materials: dict


def compile_mechanism_scheduling_train_panels(config, packets):
    if type(config) is not FrozenMechanismSchedulingTrainConfig or not isinstance(packets, tuple) or any(not isinstance(p, PublicTrainPacket) for p in packets):
        raise ContractError('typed frozen configuration and exported custody packets required')
    b = config.data(); by_item = packet_index(b, packets)
    designs = DESIGNS
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
    materials = {pair: {k: FrozenMechanismSchedulingMaterial(FrozenRecord.from_dict(v)) for k,v in entries.items()}
                 for pair, entries in b['materials_by_pair'].items()}
    panels, scenarios = [], {}
    for name in designs:
        design = registered_design(name, b['baseline_digest']); cells = []
        arms = {r['id']: FrozenRecord.from_dict(r['arm']) for r in design.data()['cells'] if r['status'] == 'executable'}
        for item in b['item_ids']:
            packet = by_item[item]
            for replicate in b['replicates']:
                scenario = FrozenRecord.from_dict({'schema': 'mechanism-scheduling-scenario-v1', 'obligation_id': name,
                    'design_digest': design.content_hash, 'task_digest': packet.task.content_hash, 'replicate': replicate,
                    'material_digest': materials[name][packet.task.content_hash].record.content_hash,
                    'source_verifier_binding': b['source_verifier_bindings'][name],
                    'recipe': recipe(name).data(), 'objective': b['objective'], 'image': b['image'], 'timeout_seconds': b['timeout_seconds']})
                for arm_id, arm in arms.items():
                    cell = PanelCell(name, packet.task.identity, replicate, 'combination', arm_id, arm,
                        packet.task.content_hash, scenario.content_hash, packages[arm.content_hash].digest,
                        FrozenRecord.from_dict(b['scorer']).content_hash)
                    cells.append(cell); scenarios[cell.key] = scenario
        panel = CombinationPanel(b['stage'], 'train', packets[0].task.identity.split_id, name, 'interaction_on_scale', design,
            FrozenRecord.from_dict({'schema': 'combination-package-bundle-v1', 'packages': {a.content_hash: packages[a.content_hash].record.data() for a in arms.values()}}),
            FrozenRecord.from_dict(b['acceptance_criteria']), tuple(cells))
        panels.append(panel)
    return CompiledMechanismSchedulingPanels(tuple(panels), packets, scenarios, packages, materials)


@dataclass(frozen=True)
class MechanismSchedulingTrainRun:
    compiled: CompiledMechanismSchedulingPanels
    results: tuple
    scores: tuple
    attempts: tuple
    contrasts: tuple
    receipt: FrozenRecord


def run_mechanism_scheduling_train_panels(config, *, custody, snapshot_root, export_root, run_root, model,
        audit_verifier, source_verifiers, provider, scoring_services, execution_authority, scorer_authority_keys,
        prospective_exporter=None):
    """Execute the complete precompiled TRAIN grid with one fresh shared ledger."""
    if (type(config) is not FrozenMechanismSchedulingTrainConfig or not isinstance(audit_verifier, AuditVerifier)
            or not isinstance(source_verifiers, dict) or set(source_verifiers) != set(DESIGNS)
            or not callable(getattr(provider, 'search', None))
            or not isinstance(scoring_services, dict) or set(scoring_services) != set(DESIGNS)
            or any(type(v) is not CombinationScorerProcessClient for v in scoring_services.values())):
        raise ContractError('exact mechanism scheduling train configuration, verifiers and scorer processes required')
    b = config.data()
    for pair in DESIGNS:
        qualifier = source_verifiers[pair]; service = scoring_services[pair]
        expected = DualMaterialVerifier
        if (type(qualifier) is not expected or qualifier.binding().data() != b['source_verifier_bindings'][pair]
                or service.mechanism_scheduling is not True or service.panel.obligation_id != pair):
            raise ContractError('pair-specific material qualifier or scorer process scope differs')
        _service_preflight(config, model, service, execution_authority, scorer_authority_keys)
        if any(a.authority.key in {execution_authority.key, *scorer_authority_keys.values()}
               or a.authority.authority_id in {execution_authority.authority_id, *scorer_authority_keys}
               for a in qualifier.authorities):
            raise ContractError('source, execution and scoring authority roles must be independent')
    snapshot, exported, root, _ = _checked_roots(snapshot_root, export_root, run_root, model.root)
    if root.exists() or exported.exists(): raise ContractError('closed controller requires unused roots and no retry')
    b = config.data()
    source = CombinationTrainSource(b, custody=custody, prospective_exporter=prospective_exporter,
                                  snapshot=snapshot, exported=exported)
    root.mkdir(parents=True)
    journal = {'schema': 'mechanism-scheduling-train-attempt-v1', 'config_digest': config.record.content_hash, 'status': 'exporting',
        'allocation': b['allocation'], 'max_model_calls': b['max_calls'], 'max_model_tokens': b['max_tokens'], 'expected_cells': 24, 'cells': [], 'actual_scorer_calls': 0}
    def persist():
        journal['actual_model_usage'] = _usage(model); _write(root/'controller-attempt.json', journal)
    persist()
    try:
        packets = source.export()
        journal['packet_receipts'] = [p.receipt.data() for p in packets]; persist()
        compiled = compile_mechanism_scheduling_train_panels(config, packets)
        # Freeze every planned denominator before any source, model, or scorer call.
        journal.update(panels=[{'digest': p.digest, 'design': p.design.data(), 'cells': [c.data() for c in p.cells]} for p in compiled.panels],
            cells=[{'cell': c.data(), 'status': 'not_started', 'phase': 'planned', 'scorer_calls': 0, 'docker_attempts': 0}
                   for p in compiled.panels for c in p.cells])
        persist()
        if any(scoring_services[p.obligation_id].panel != p for p in compiled.panels):
            raise ContractError('scorer process differs from the exact compiled panel')
        broker = DockerExecutionBroker([exported, root])
        by_task = {p.task.content_hash: p for p in packets}
        # Check all deterministic materials and bytes before any external authority/model call.
        for panel in compiled.panels:
            for cell in panel.cells:
                material = compiled.materials[panel.obligation_id][cell.task_digest]; task = by_task[cell.task_digest].task
                check_inputs(material.scheduling(), task, broker, {'public_csv': by_task[cell.task_digest].csv_path})
                if material.data()['kind'] == 'retrieval':
                    check_retrieval(FrozenRecord.from_dict(material.data()['mechanism']), task)
        journal['status'] = 'executing'; persist()
    except Exception as exc:
        for row in journal['cells']:
            row.update(status='blocked', phase='preflight', reason='blocked_before_execution')
        journal.update(status='blocked_before_execution', error_type=type(exc).__name__); persist(); raise
    results, scores, score_inputs, runtime_by_panel = [], [], {}, {}
    for index, (panel, cell) in enumerate((p,c) for p in compiled.panels for c in p.cells):
        service = scoring_services[panel.obligation_id]
        source_verifier = source_verifiers[panel.obligation_id]
        row = journal['cells'][index]; result = None
        row.update(status='running', phase='material_verification', model_usage_before=_usage(model)); persist()
        cell_root = root/'cells'/FrozenRecord.from_dict(cell.data()).content_hash
        try:
            if model.ledger['usage_incomplete']:
                row.update(status='blocked', phase='model_allocation', reason='prior_usage_incomplete'); continue
            packet = by_task[cell.task_digest]
            args = dict(panel=panel, task=packet.task, scenario=compiled.scenarios[cell.key],
                package=compiled.packages[cell.runtime_arm.content_hash], material=compiled.materials[panel.obligation_id][cell.task_digest],
                source_verifier=source_verifier, public_inputs={'public_csv': packet.csv_path}, broker=broker)
            result = run_mechanism_scheduling_cell(cell=cell, **args, provider=provider, objective=FrozenRecord.from_dict(b['objective']),
                sidecar=cell_root, image=b['image'], model=model, audit_verifier=audit_verifier, timeout_seconds=b['timeout_seconds'])
            row.update(phase='source_verification', runtime=PanelReceiptVerifier._runtime_data(result.runtime)); persist()
            if result.cell != cell or result.runtime.cell_key != cell.key: raise ContractError('foreign executor cell')
            verified = verify_mechanism_scheduling_cell(result, **args)
            row['verification'] = verified.data(); runtime_by_panel.setdefault(panel.digest, []).append(result.runtime)
            if result.runtime.status != 'succeeded':
                row.update(status='failed', phase='execution', reason='original_execution_failure'); continue
            source = issue_mechanism_scheduling_score_input(authority=execution_authority, result=result, **args); score_inputs[cell.key] = source
            row.update(phase='scoring', scorer_calls=1, score_input=source.data()); journal['actual_scorer_calls'] += 1; persist()
            score = service.score_combination(panel=panel, cell=cell, score_input=source)
            row.update(phase='score_verification', scorer_receipt=score.receipt.data())
            verify_combination_adapted_receipt(score, authority_keys=scorer_authority_keys, config=service.config, panel=panel,
                cell=cell, score_input=source, execution_authority_keys={execution_authority.authority_id: execution_authority.key})
            scores.append(score); row.update(status='succeeded', phase='verified')
        except Exception as exc:
            row.update(status='failed', error_type=type(exc).__name__)
        finally:
            row['model_usage_after'] = _usage(model)
            source_path = cell_root/'source-verification.json'
            if source_path.is_file():
                import json
                row['source_verification'] = json.loads(source_path.read_text(encoding='utf-8'))
                row['source_sha256'] = hashlib.sha256(source_path.read_bytes()).hexdigest()
            phase_path = cell_root/'phase'/'receipt.json'
            phase_events = cell_root/'phase'/'events.jsonl'
            if phase_path.is_file():
                import json
                row['phase_receipt'] = json.loads(phase_path.read_text(encoding='utf-8'))
            row['auxiliary_docker_attempts'] = (sum(FrozenRecord(line).data()['kind'] == 'start'
                for line in phase_events.read_text(encoding='utf-8').splitlines()) if phase_events.is_file() else 0)
            if result:
                trace = [FrozenRecord(line).data() for line in result.runtime.trace_path.read_text(encoding='utf-8').splitlines()]
                row['retrieval_calls'] = sum(e['stage']=='q8_retrieval_request' for e in trace)
                row['retrieval_items'] = sum(e['stage']=='q8_retrieval_item' for e in trace)
                row['retrieval_failures'] = [e['data'] for e in trace if e['stage']=='q8_retrieval_failure']
                row['retrieval_budget'] = [e['data'] for e in trace if e['stage']=='q8_retrieval_budget']
            if result and result.solver and result.solver.execution: row['execution_receipt'] = result.solver.execution.data()
            row['docker_attempts'] = (sum(FrozenRecord(line).data()['stage'] == 'execution_request'
                for line in result.runtime.trace_path.read_text(encoding='utf-8').splitlines()) if result else 0)
            row['docker_attempts'] += row['auxiliary_docker_attempts']
            results.append(result); persist()
    contrasts = []
    for panel in compiled.panels:
        service = scoring_services[panel.obligation_id]
        source_verifier = source_verifiers[panel.obligation_id]
        def verify_score(score, cell, owner):
            verify_combination_adapted_receipt(score, authority_keys=scorer_authority_keys, config=service.config, panel=owner,
                cell=cell, score_input=score_inputs[cell.key], execution_authority_keys={execution_authority.authority_id: execution_authority.key})
        try:
            contrast = estimate_grouped_contrast(panel, runtime=runtime_by_panel.get(panel.digest, []),
                scorer_receipts=[s for s in scores if s.cell_key in {c.key for c in panel.cells}],
                verifier=CombinationPanelVerifier(scorer_verifier=verify_score))
        except Exception as exc:
            contrast = FrozenRecord.from_dict({'schema': 'mechanism-scheduling-inconclusive-contrast-v1', 'panel_digest': panel.digest,
                'status': 'inconclusive', 'reason': 'incomplete_or_failed_cell', 'error_type': type(exc).__name__})
        contrasts.append(contrast)
    receipt = FrozenRecord.from_dict({'schema': 'mechanism-scheduling-train-receipt-v1', 'config_digest': config.record.content_hash,
        'expected_cells': 24, 'observed_cells': len(results), 'scored_cells': len(scores),
        'failed_cells': sum(r['status']=='failed' for r in journal['cells']), 'blocked_cells': sum(r['status']=='blocked' for r in journal['cells']),
        'allocation': b['allocation'], 'actual_model_usage': _usage(model), 'actual_scorer_calls': journal['actual_scorer_calls'],
        'actual_docker_attempts': sum(r['docker_attempts'] for r in journal['cells']),
        'unused_model_opportunities': b['max_calls'] - len(model.ledger['calls']),
        'unused_docker_opportunities': 72 - sum(r['docker_attempts'] for r in journal['cells']),
        'scorer_usage_unknown': journal['actual_scorer_calls'] > 0,
        'unused_scorer_opportunities': 24-journal['actual_scorer_calls'],
        'source_calls': sum(len(r.get('source_verification', {}).get('calls', [])) for r in journal['cells']),
        'auxiliary_docker_attempts': sum(r.get('auxiliary_docker_attempts', 0) for r in journal['cells']),
        'phase_unknown_cost_attempts': sum(r.get('phase_receipt', {}).get('unknown_cost_attempts', 0) for r in journal['cells']),
        'retrieval_calls': sum(r.get('retrieval_calls',0) for r in journal['cells']),
        'unused_retrieval_opportunities': 24 - sum(r.get('retrieval_calls',0) for r in journal['cells']),
        'contrasts': [c.data() for c in contrasts], 'pruned_cells': [], 'scientific_effectiveness_proven': False, 'validation_opened': False,
        'status': 'complete_train_engineering' if len(scores)==len(results)==24
            and all(c.data()['status'] in {'estimated', 'not_identifiable'} for c in contrasts) else 'inconclusive'})
    _write(root/'controller-receipt.json', receipt.data()); journal['status'] = receipt.data()['status']; persist()
    return MechanismSchedulingTrainRun(compiled, tuple(results), tuple(scores), tuple(FrozenRecord.from_dict(r) for r in journal['cells']), tuple(contrasts), receipt)
