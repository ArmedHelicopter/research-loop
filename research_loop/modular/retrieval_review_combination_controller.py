"""Three closed retrieval/review designs, one shared session per cell."""
from research_loop.modular.train_provider_preflight import (native_envelope, native_source_fields, response_schemas, validate_native_declaration)
from research_loop.modular.ordinary_provider import (family_service_preflight, model_root, allocation_fields, provider_usage, provider_terminal, unused_main_opportunities, provider_scope, bind_runtime_originals)
from research_loop.modular.phase_provider import PhaseProviderSession
from dataclasses import dataclass
import hashlib
from pathlib import Path

from evaluation.modular.train_io import PublicTrainPacket
from research_loop.modular.combination_train_source import (
    CombinationTrainSource, source_schema_matches, source_item_matches, packet_index,
)
from evaluation.modular.scoring_service import ScorerConfig
from evaluation.modular.combination_scoring import _score_input_payload, verify_combination_adapted_receipt
from evaluation.modular.scorer_process import CombinationScorerProcessClient
from research_loop.modular.combination_train_controller import _service_preflight, _usage, _ANALYSIS, _digest, _names
from research_loop.modular.combination_panels import CombinationPanel, CombinationPanelVerifier
from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.contracts import FrozenRecord, DataIdentity
from research_loop.modular.retrieval_review_combination_driver import (DESIGNS, SLOTS, BUDGET, registered_design,
    run_retrieval_review_cell, verify_retrieval_review_cell, freeze_material, check_material)
from research_loop.modular.model_port import _validate_schema, _schema_witness
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.panel_receipts import PanelCell, PanelReceiptVerifier
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import _checked_roots, _write
from research_loop.ontology import ContractError


def _arms(baseline):
    return {row['arm_digest']: FrozenRecord.from_dict(row['arm']) for name in DESIGNS
            for row in registered_design(name, baseline).data()['cells'] if row['status'] == 'executable'}


@dataclass(frozen=True)
class FrozenRetrievalReviewConfig:
    record: FrozenRecord

    def __post_init__(self):
        if not isinstance(self.record, FrozenRecord): raise ContractError('frozen retrieval review train configuration required')
        b = self.data(); native = native_envelope(b, 'retrieval_review')
        required = {'schema', 'domain', 'stage', 'item_ids', 'task_bindings', 'baseline_digest', 'packages_by_arm',
            'scorer', 'scorer_handle_bindings', 'acceptance_criteria', 'replicates', 'model', 'effort', 'max_calls',
            'max_tokens', 'schemas', 'allocation', 'image', 'timeout_seconds', 'materials_by_task'}
        if (not (source_schema_matches(b, required, 'retrieval-review-combination-train-config-v1') or native_source_fields(b, required, family='retrieval_review')) or b['domain'] != 'train'
                or not isinstance(b['stage'], str) or not b['stage'].strip() or not _names(b['item_ids'])
                or not _names(b['replicates']) or not _digest(b['baseline_digest'])):
            raise ContractError('closed retrieval review train scope or source list invalid')
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
            m = b['materials_by_task'][row['task_digest']]
            if not isinstance(m, dict) or m.get('identity') != row['identity'] or m.get('task_digest') != row['task_digest'] or m.get('budget') != BUDGET:
                raise ContractError('material must bind exact task and equal total retrieval budget')
        arms = _arms(b['baseline_digest'])
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
        n = len(identities) * len(b['replicates']) * 16
        allocation = {'model_slots_per_cell': list(SLOTS), 'docker_attempts_per_cell': 1, 'scorer_calls_per_cell': 1,
            'scorer_call_limit': n, 'scorer_token_accounting': 'transport_not_provided', 'source_calls_per_cell': 3, 'source_cap_per_cell': 3, 'context_bytes_per_cell': 4096}
        if FrozenRecord.from_dict(b['allocation']) != FrozenRecord.from_dict(allocation):
            raise ContractError('five model, one Docker, three source and one scorer allocations must match')
        if ((not native and (b['model'] != 'gpt-5.6-luna' or b['effort'] != 'low' or type(b['max_calls']) is not int or b['max_calls'] != n*5
                or type(b['max_tokens']) is not int or b['max_tokens'] < 1)) or type(b['timeout_seconds']) is not int
                or not 1 <= b['timeout_seconds'] <= 120 or not isinstance(b['image'], str) or '@sha256:' not in b['image']
                or not _digest(b['image'].rsplit('@sha256:', 1)[1])):
            raise ContractError('bounded matched model and pinned Docker configuration required')
        schemas = response_schemas(b, family='retrieval_review')
        if not isinstance(schemas, dict) or set(schemas) != set(SLOTS): raise ContractError('exact five shared response schemas required')
        for schema in schemas.values():
            if not isinstance(schema, dict) or schema.get('type') != 'object': raise ContractError('object response schema required')
            _validate_schema(schema, _schema_witness(schema))
        if native:
            validate_native_declaration(b, family='retrieval_review', schemas=schemas, main_opportunities=n*5)

    def data(self): return self.record.data()


@dataclass(frozen=True)
class CompiledRetrievalReviewPanels:
    panels: tuple
    packets: tuple
    scenarios: dict
    packages: dict
    materials: dict


def compile_retrieval_review_panels(config, packets):
    if not isinstance(config, FrozenRetrievalReviewConfig) or not isinstance(packets, tuple) or any(not isinstance(p, PublicTrainPacket) for p in packets):
        raise ContractError('typed frozen configuration and exported custody packets required')
    b = config.data(); by_item = packet_index(b, packets)
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
    materials = {k: FrozenRecord.from_dict(v) for k,v in b['materials_by_task'].items()}
    panels, scenarios = [], {}
    for name in DESIGNS:
        design = registered_design(name, b['baseline_digest']); cells = []
        arms = {r['id']: FrozenRecord.from_dict(r['arm']) for r in design.data()['cells'] if r['status'] == 'executable'}
        for item in b['item_ids']:
            packet = by_item[item]
            for replicate in b['replicates']:
                scenario = FrozenRecord.from_dict({'schema': 'retrieval-review-combination-scenario-v1', 'obligation_id': name,
                    'design_digest': design.content_hash, 'task_digest': packet.task.content_hash, 'replicate': replicate,
                    'material_digest': materials[packet.task.content_hash].content_hash})
                for arm_id, arm in arms.items():
                    cell = PanelCell(name, packet.task.identity, replicate, 'combination', arm_id, arm,
                        packet.task.content_hash, scenario.content_hash, packages[arm.content_hash].digest,
                        FrozenRecord.from_dict(b['scorer']).content_hash)
                    cells.append(cell); scenarios[cell.key] = scenario
        panel = CombinationPanel(b['stage'], 'train', packets[0].task.identity.split_id, name, 'interaction_on_scale', design,
            FrozenRecord.from_dict({'schema': 'combination-package-bundle-v1', 'packages': {a.content_hash: packages[a.content_hash].record.data() for a in arms.values()}}),
            FrozenRecord.from_dict(b['acceptance_criteria']), tuple(cells))
        panels.append(panel)
    return CompiledRetrievalReviewPanels(tuple(panels), packets, scenarios, packages, materials)


@dataclass(frozen=True)
class RetrievalReviewRun:
    compiled: CompiledRetrievalReviewPanels
    results: tuple
    scores: tuple
    attempts: tuple
    contrasts: tuple
    receipt: FrozenRecord


def run_retrieval_review_panels(config, *, custody, snapshot_root, export_root, run_root, model, audit_verifier,
        provider, admission_port, execution_authority, scoring_services, scorer_authority_keys, prospective_exporter=None):
    if (not isinstance(config, FrozenRetrievalReviewConfig)
            or not isinstance(audit_verifier, AuditVerifier) or not callable(getattr(provider, 'search', None))
            or not callable(admission_port) or not isinstance(scoring_services, dict) or set(scoring_services) != set(DESIGNS)
            or any(not isinstance(v, CombinationScorerProcessClient) for v in scoring_services.values())):
        raise ContractError('closed train dependencies and separate scorer processes required')
    for service in scoring_services.values():
        family_service_preflight(config, model, service, execution_authority, scorer_authority_keys, family='retrieval_review')
    native = native_envelope(config.data(), 'retrieval_review')
    snapshot, exported, root, _ = _checked_roots(snapshot_root, export_root, run_root, model_root(model, native=native))
    if root.exists() or exported.exists(): raise ContractError('closed controller requires unused roots and no retry')
    b = config.data()
    source = CombinationTrainSource(b, custody=custody, prospective_exporter=prospective_exporter,
                                  snapshot=snapshot, exported=exported)
    root.mkdir(parents=True)
    provider_session = PhaseProviderSession(model, root/'provider-scopes.json') if native else None
    journal = {'schema': ('retrieval-review-train-attempt-v2' if native else 'retrieval-review-train-attempt-v1'), 'config_digest': config.record.content_hash, 'status': 'exporting',
        'allocation': b['allocation'], **allocation_fields(b, native=native), 'cells': [], 'actual_scorer_calls': 0}
    def persist():
        journal['actual_model_usage'] = provider_usage(provider_session, model); _write(root/'controller-attempt.json', journal)
    persist()
    try:
        packets = source.export()
        journal['packet_receipts'] = [p.receipt.data() for p in packets]; persist()
        compiled = compile_retrieval_review_panels(config, packets)
        if any(scoring_services[p.obligation_id].panel != p for p in compiled.panels):
            raise ContractError('scorer process does not bind the exact compiled panel')
        broker = DockerExecutionBroker([exported, root])
        by_task = {p.task.content_hash: p for p in packets}
        for packet in packets:
            check_material(compiled.materials[packet.task.content_hash], packet.task)
        journal.update(status='executing', panels=[{'digest': p.digest, 'design': p.design.data(), 'cells': [c.data() for c in p.cells]} for p in compiled.panels],
            packet_receipts=[p.receipt.data() for p in packets],
            cells=[{'cell': c.data(), 'status': 'not_started', 'phase': 'planned', 'scorer_calls': 0} for p in compiled.panels for c in p.cells])
        persist()
    except Exception as exc:
        journal.update(status='blocked_before_execution', error_type=type(exc).__name__); persist(); raise
    results, scores, score_inputs, runtime_by_panel = [], [], {}, {}
    for index, (panel, cell) in enumerate((p,c) for p in compiled.panels for c in p.cells):
        row = journal['cells'][index]; result = None
        row.update(status='running', phase='material_verification', model_usage_before=provider_usage(provider_session, model)); persist()
        cell_root = root/'cells'/FrozenRecord.from_dict(cell.data()).content_hash
        try:
            if provider_terminal(provider_session, model):
                row.update(status='blocked', phase='model_allocation', reason='prior_usage_incomplete'); continue
            packet = by_task[cell.task_digest]
            scoring_service = scoring_services[panel.obligation_id]
            args = dict(panel=panel, task=packet.task, scenario=compiled.scenarios[cell.key],
                package=compiled.packages[cell.runtime_arm.content_hash], material=compiled.materials[cell.task_digest],
                public_inputs={'public_csv': packet.csv_path}, broker=broker)
            with provider_scope(provider_session, model, cell) as scoped_model:
                result = run_retrieval_review_cell(cell=cell, **args, provider=provider, admission_port=admission_port, objective=FrozenRecord.from_dict({'panel_digest': panel.digest}),
                    sidecar=cell_root, image=b['image'], model=scoped_model, audit_verifier=audit_verifier, timeout_seconds=b['timeout_seconds'])
            row.update(phase='source_verification', runtime=PanelReceiptVerifier._runtime_data(result.runtime)); persist()
            if result.cell != cell or result.runtime.cell_key != cell.key: raise ContractError('foreign executor cell')
            verified = verify_retrieval_review_cell(result, **args)
            row['verification'] = verified.data(); runtime_by_panel.setdefault(panel.digest, []).append(result.runtime)
            if result.runtime.status != 'succeeded':
                row.update(status='failed', phase='execution', reason='original_execution_failure'); continue
            source = execution_authority.issue(_score_input_payload(panel, result).data()); score_inputs[cell.key] = source
            if native:
                row['provider_seal_digest'] = bind_runtime_originals(provider_session, cell, result.runtime, cell_root/'provider-seal.json')
            row.update(phase='scoring', scorer_calls=1, score_input=source.data()); journal['actual_scorer_calls'] += 1; persist()
            score = scoring_service.score_combination(panel=panel, cell=cell, score_input=source)
            row.update(phase='score_verification', scorer_receipt=score.receipt.data())
            verify_combination_adapted_receipt(score, authority_keys=scorer_authority_keys, config=scoring_service.config, panel=panel,
                cell=cell, score_input=source, execution_authority_keys={execution_authority.authority_id: execution_authority.key})
            scores.append(score); row.update(status='succeeded', phase='verified')
        except Exception as exc:
            row.update(status='failed', error_type=type(exc).__name__)
        finally:
            row['model_usage_after'] = provider_usage(provider_session, model)
            if result:
                ev = [FrozenRecord(line).data() for line in result.runtime.trace_path.read_text(encoding='utf-8').splitlines()]
                row['source_calls'] = sum(e['stage']=='q8_retrieval_request' for e in ev)
                row['source_items'] = sum(e['stage']=='q8_retrieval_item' for e in ev)
                row['source_failures'] = [e['data'] for e in ev if e['stage']=='q8_retrieval_failure']
                row['retrieval_budget'] = [e['data'] for e in ev if e['stage']=='q8_retrieval_budget']
            if result and result.solver and result.solver.execution: row['execution_receipt'] = result.solver.execution.data()
            row['docker_attempts'] = (sum(FrozenRecord(line).data()['stage'] == 'execution_request'
                for line in result.runtime.trace_path.read_text(encoding='utf-8').splitlines()) if result else 0)
            results.append(result); persist()
    contrasts = []
    for panel in compiled.panels:
        def verify_score(score, cell, owner):
            verify_combination_adapted_receipt(score, authority_keys=scorer_authority_keys, config=scoring_services[owner.obligation_id].config, panel=owner,
                cell=cell, score_input=score_inputs[cell.key], execution_authority_keys={execution_authority.authority_id: execution_authority.key})
        try:
            contrast = estimate_grouped_contrast(panel, runtime=runtime_by_panel.get(panel.digest, []),
                scorer_receipts=[s for s in scores if s.cell_key in {c.key for c in panel.cells}],
                verifier=CombinationPanelVerifier(scorer_verifier=verify_score))
        except Exception as exc:
            contrast = FrozenRecord.from_dict({'schema': 'retrieval-review-inconclusive-contrast-v1', 'panel_digest': panel.digest,
                'status': 'inconclusive', 'reason': 'incomplete_or_failed_cell', 'error_type': type(exc).__name__})
        contrasts.append(contrast)
    receipt = FrozenRecord.from_dict({'schema': ('retrieval-review-train-receipt-v2' if native else 'retrieval-review-train-receipt-v1'), 'config_digest': config.record.content_hash,
        'expected_cells': len(journal['cells']), 'observed_cells': len(results), 'scored_cells': len(scores),
        'failed_cells': sum(r['status']=='failed' for r in journal['cells']), 'blocked_cells': sum(r['status']=='blocked' for r in journal['cells']),
        'allocation': b['allocation'], 'actual_model_usage': provider_usage(provider_session, model), 'actual_scorer_calls': journal['actual_scorer_calls'],
        'actual_docker_attempts': sum(r['docker_attempts'] for r in journal['cells']),
        'unused_model_opportunities': unused_main_opportunities(provider_session, model, b),
        'unused_docker_opportunities': len(results) - sum(r['docker_attempts'] for r in journal['cells']),
        'scorer_usage_unknown': journal['actual_scorer_calls'] > 0,
        'source_calls': sum(r.get('source_calls', 0) for r in journal['cells']),
        'unused_source_call_opportunities': len(results)*3-sum(r.get('source_calls',0) for r in journal['cells']),
        'source_items': sum(r.get('source_items',0) for r in journal['cells']),
        'verified_source_cost': {'units': None, 'status': 'unknown'},
        'mechanism_endpoint_independently_scored': False, 'primary_score_role': 'companion_interface_only',
        'contrasts': [c.data() for c in contrasts], 'pruned_cells': [], 'scientific_effectiveness_proven': False, 'validation_opened': False,
        'status': 'complete_engineering_grid_with_scientific_endpoint_gap' if len(scores)==len(results)
            and all(c.data()['status'] in {'estimated', 'not_identifiable'} for c in contrasts) else 'inconclusive'})
    _write(root/'controller-receipt.json', receipt.data()); journal['status'] = receipt.data()['status']; persist()
    return RetrievalReviewRun(compiled, tuple(results), tuple(scores), tuple(FrozenRecord.from_dict(r) for r in journal['cells']), tuple(contrasts), receipt)
