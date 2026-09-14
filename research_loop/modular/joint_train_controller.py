"""Execute and independently score the complete C5 common TRAIN grid.

This is an engineering controller only.  It does not select a recipe, issue a
deployment grant, open validation inputs, or make a scientific claim.  The
runtime plan fixes 46 canonical history builds and 118 target cells; a target
cannot be dispatched until the complete original history barrier is sealed.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from evaluation.modular.combination_scoring import (
    _score_input_payload,
    verify_combination_adapted_receipt,
    verify_combination_score_input,
)
from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from evaluation.modular.scorer_process import CombinationScorerProcessClient
from evaluation.modular.scoring_service import ScorerConfig
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.full_loo_driver import verify_stage
from research_loop.modular.full_loo_modules import slots
from research_loop.modular.joint_train_panel import JointTrainPanel, history_build_id
from research_loop.modular.joint_train_runtime import (
    FrozenJointTrainRuntimePlan,
    JointTrainBarrier,
    JointTrainStage,
    JointTrainStageExecutor,
    compile_panel,
    _barrier_validation_scope,
    _compile_panel_from_context,
    _VerifiedJointTrainBarrier,
)
from research_loop.modular.metaprogram_training import _Journal, _exclusive
from research_loop.modular.phase_provider import PhaseProviderAbort, PhaseProviderLedger, call_accounting
from research_loop.ontology import ContractError


R = FrozenRecord.from_dict
_SCHEMA = 'c5-common-train-controller-receipt-v1'


def _scope(stage: JointTrainStage) -> str:
    return stage.record.data()['scope_id']


def _native_accounting(executor: JointTrainStageExecutor) -> dict:
    """Capture inspectable provider use before the final fresh ledger replay."""
    usage = executor.session.usage().data()
    if usage.get('schema') == 'public-train-provider-usage-v1':
        calls = usage['main_opportunities']
        if usage['unknown_main_opportunities']:
            return {'schema': 'train-phase-terminal-accounting-v2', 'provider_calls_lower_bound': calls,
                    'known_reported_tokens_lower_bound': usage['known_reported_tokens'],
                    'known_usage_scope': usage['known_usage_scope'], 'unknown_unobserved_opportunities': True,
                    'title_tokens': None, 'all_opportunity_tokens': None, 'settled_additional_charge_usd': None,
                    'score_eligible': False}
        return {'schema': 'train-phase-call-accounting-v2', 'provider_calls': calls,
                'known_reported_tokens': usage['known_reported_tokens'], 'known_usage_scope': usage['known_usage_scope'],
                'unknown_main_opportunities': 0, 'unsuccessful_opportunities': 0,
                'possible_initial_title_opportunities': usage['possible_initial_title_opportunities'],
                'title_tokens': None, 'all_opportunity_tokens': None, 'settled_additional_charge_usd': None}
    # A PhaseProviderAbort snapshot is accounting evidence, never an eligible seal.
    return {'schema': 'train-phase-terminal-accounting-v2',
            'provider_calls_lower_bound': usage['observed_main_opportunities_lower_bound'],
            'known_reported_tokens_lower_bound': usage['known_reported_tokens_lower_bound'],
            'known_usage_scope': 'native_main', 'unknown_unobserved_opportunities': True,
            'title_tokens': None, 'all_opportunity_tokens': None, 'settled_additional_charge_usd': None,
            'score_eligible': False}


def _actual(stages: tuple[JointTrainStage, ...], accounting: dict, rows: list[dict]) -> dict:
    source_calls, corpus_calls = [], []
    auxiliary = solver = retrieval = builders = 0
    for stage in stages:
        root = stage.inner.root
        for name, destination in (('source/source.json', source_calls), ('corpus/source.json', corpus_calls)):
            path = root / name
            if path.exists():
                destination.extend(json.loads(path.read_bytes())['calls'])
        trace = root / 'runtime/trace.jsonl'
        events = [json.loads(line) for line in trace.read_bytes().splitlines()] if trace.exists() else []
        solver += sum(event['stage'] == 'execution_request' for event in events)
        retrieval += sum(event['stage'] == 'q8_retrieval_request' for event in events)
        builders += sum(event['stage'] == 'c4_builder_request' for event in events)
        phase = root / 'phase/events.jsonl'
        if phase.exists():
            auxiliary += sum(json.loads(line)['kind'] == 'start' for line in phase.read_bytes().splitlines())
    return {'model_calls': accounting.get('provider_calls'), 'builder_executions': builders,
            'independent_source_qualification_calls': len(source_calls), 'corpus_qualification_calls': len(corpus_calls),
            'retrieval_requests': retrieval, 'auxiliary_docker_attempts': auxiliary,
            'solver_docker_attempts': solver, 'docker_attempts': auxiliary + solver,
            'scorer_calls': sum(row['scorer_calls'] for row in rows)}


def _verify_target(stage: JointTrainStage, *, barrier: JointTrainBarrier, panel: JointTrainPanel,
                   ledger: PhaseProviderLedger) -> None:
    """Bind one scorer input to the final target seal and the actual stage."""
    if type(stage) is not JointTrainStage or type(barrier) is not JointTrainBarrier or type(panel) is not JointTrainPanel:
        raise ContractError('typed common target and panel required')
    with _barrier_validation_scope(barrier) as context:
        _verify_target_in_context(stage, barrier=barrier, panel=panel, ledger=ledger, context=context)


def _verify_target_in_context(stage: JointTrainStage, *, barrier: JointTrainBarrier, panel: JointTrainPanel,
                              ledger: PhaseProviderLedger, context) -> None:
    """Private target replay under one already-fresh active barrier lease."""
    if type(context) is not _VerifiedJointTrainBarrier:
        raise ContractError('exact active common barrier lease required')
    context.require(barrier)
    expected_panel, _ = _compile_panel_from_context(context)
    if panel != expected_panel or stage.inner.cell not in panel.cells:
        raise ContractError('common scorer panel differs from sealed history barrier')
    executor = barrier.executor
    with executor._predispatch_verification_pass() as passed:
        executor._verify(stage, context, passed)
    body = stage.record.data()
    if body['stage'] != 'target' or body['history_barrier_digest'] != barrier.record.content_hash:
        raise ContractError('common target did not bind its sealed history barrier')
    recipe = next(recipe for recipe in executor.plan.recipes if recipe['id'] == stage.inner.cell.arm_id)
    calls = ledger.calls_for_scope(_scope(stage))
    if tuple(call.data()['slot'] for call in calls) != slots(recipe, 'target'):
        raise ContractError('common target scope has a missing, foreign, or reordered slot')
    packet = next(packet for packet in executor.plan.packets if packet.task.content_hash == stage.inner.cell.task_digest)
    verify_stage(stage.inner, plan=executor.plan, recipe=recipe, stage='target', task=packet.task,
                 package=context.package(recipe), material=executor.plan.material(packet.task.content_hash),
                 phase_material=executor.plan.phase_material(packet.task.content_hash), source_verifier=executor.source,
                 corpus_verifier=executor.corpus, broker=executor.broker, inputs={'public_csv': packet.csv_path},
                 ledger=ledger, provider_scope_id=_scope(stage), require_provider_eligible=True)


@dataclass(frozen=True)
class JointCommonTrainRun:
    root: Path
    plan: FrozenJointTrainRuntimePlan
    executor: JointTrainStageExecutor
    barrier: JointTrainBarrier | None
    panel: JointTrainPanel | None
    builds: tuple[JointTrainStage, ...]
    targets: tuple[JointTrainStage | None, ...]
    target_ledger: PhaseProviderLedger | PhaseProviderAbort
    score_inputs: tuple[FrozenRecord, ...]
    scores: tuple[object, ...]
    receipt: FrozenRecord


def run_joint_common_train(executor: JointTrainStageExecutor, *, scorer_factory: Callable[[JointTrainPanel], object],
                           execution_authority: LinkedExecutionAuthority, scorer_authority_keys: dict[str, bytes]) -> JointCommonTrainRun:
    """Run all 46+118 opportunities and score only after a final target seal."""
    if (type(executor) is not JointTrainStageExecutor or not callable(scorer_factory)
            or type(execution_authority) is not LinkedExecutionAuthority or not isinstance(scorer_authority_keys, dict)
            or executor.stages or executor.poisoned):
        raise ContractError('fresh exact common executor, scorer factory, and independent authority required')
    plan = executor.plan
    plan.__post_init__()
    root = executor.root
    journal = _Journal(root / 'common-controller.jsonl')
    build_rows = [{'build_id': history_build_id(plan.protocol, recipe),
                   'recipe_id': recipe['id'], 'status': 'not_started'} for recipe in plan.builds]
    rows = [{'arm_id': recipe['id'], 'task_digest': packet.task.content_hash, 'status': 'not_started', 'scorer_calls': 0}
            for recipe in plan.recipes for packet in plan.packets]
    allocation = plan.protocol.record.data()['allocation']
    if (len(plan.recipes) != 59 or len(build_rows) != allocation['unique_canonical_builds']
            or len(rows) != allocation['target_cells']
            or allocation['executable_arm_procedures'] != len(plan.recipes)
            or allocation['target_cells'] != len(plan.recipes) * len(plan.packets)):
        raise ContractError('common controller grid differs from the frozen recipe and target denominators')

    def persist(captured: dict | None = None) -> None:
        body = {'schema': 'c5-common-train-controller-attempts-v1', 'plan_digest': plan.record.content_hash,
                'builds': build_rows, 'targets': rows, 'allocation': plan.protocol.record.data()['allocation'],
                'provider_accounting': _native_accounting(executor) if captured is None else captured,
                'complete_history_barrier': False, 'target_provider_sealed': False,
                'selection_opened': False, 'validation_opened': False}
        path = root / 'common-controller-attempts.json'
        raw = R(body).encoded.encode('utf-8')
        temporary = path.with_suffix('.tmp'); temporary.write_bytes(raw); temporary.replace(path)

    journal.append('controller_lock', {'plan_digest': plan.record.content_hash, 'allocation': plan.protocol.record.data()['allocation']})
    persist()
    builds: list[JointTrainStage] = []
    barrier = None
    panel = None
    target_map: dict[tuple[str, str], JointTrainStage | None] = {}
    targets: list[JointTrainStage | None] = []
    target_ledger: PhaseProviderLedger | PhaseProviderAbort
    service = None
    scores: list[object] = []
    score_inputs: list[FrozenRecord] = []
    process = {'startup_attempts': 0, 'startup_status': 'not_started', 'close_attempts': 0, 'closed': None, 'error': None}
    scorer_provider_terminal = False

    for row, recipe in zip(build_rows, plan.builds, strict=True):
        if executor.poisoned or executor.session.terminal():
            row.update(status='blocked', reason='prior_history_failure_or_terminal'); persist(); continue
        journal.append('build_reserved', {'build_id': row['build_id'], 'recipe_id': recipe['id']}); persist()
        try:
            result = executor.execute(recipe_id=recipe['id'], stage='history_build')
            builds.append(result)
            row.update(status=result.record.data()['status'], receipt_digest=result.record.content_hash)
            if row['status'] != 'succeeded': row['reason'] = 'history_stage_failed'
        except Exception as exc:
            row.update(status='failed', reason=type(exc).__name__ + ': ' + str(exc))
        journal.append('build_completed', {'build_id': row['build_id'], 'status': row['status']}); persist()

    if (not executor.poisoned and len(builds) == len(build_rows)
            and all(row['status'] == 'succeeded' for row in build_rows)):
        try:
            barrier = JointTrainBarrier.seal(executor)
            with _barrier_validation_scope(barrier) as context:
                panel, scenarios = _compile_panel_from_context(context)
            journal.append('complete_history_barrier', {'digest': barrier.record.content_hash, 'panel_digest': panel.digest})
        except Exception as exc:
            journal.append('history_barrier_failed', {'error_type': type(exc).__name__})
            barrier = panel = None
    else:
        scenarios = {}

    for row in rows:
        key = (row['arm_id'], row['task_digest'])
        if barrier is None or panel is None or executor.poisoned or executor.session.terminal():
            row.update(status='blocked', reason='complete_history_barrier_unavailable')
            target_map[key] = None; targets.append(None); journal.append('target_blocked', {'arm_id': key[0], 'task_digest': key[1]}); persist(); continue
        recipe = next(recipe for recipe in plan.recipes if recipe['id'] == key[0])
        build = next(build for build in barrier.builds if build.record.data()['build_id'] ==
                     history_build_id(plan.protocol, recipe))
        journal.append('target_reserved', {'arm_id': key[0], 'task_digest': key[1]}); persist()
        try:
            result = executor.execute(recipe_id=key[0], stage='target', target_digest=key[1], build=build, barrier=barrier)
            row.update(status=result.record.data()['status'], receipt_digest=result.record.content_hash)
            if row['status'] != 'succeeded': row['reason'] = 'target_stage_failed'
        except Exception as exc:
            result = None
            row.update(status='failed', reason=type(exc).__name__ + ': ' + str(exc))
        target_map[key] = result; targets.append(result)
        journal.append('target_completed', {'arm_id': key[0], 'task_digest': key[1], 'status': row['status']}); persist()

    target_ledger = executor.session.finish(root / 'complete-target-provider-ledger.json')
    journal.append('target_provider_finished', {'kind': type(target_ledger).__name__, 'eligible': type(target_ledger) is PhaseProviderLedger})
    all_targets = (barrier is not None and panel is not None and not executor.poisoned
                   and type(target_ledger) is PhaseProviderLedger and len(targets) == len(rows)
                   and all(target is not None and row['status'] == 'succeeded' for target, row in zip(targets, rows, strict=True)))

    try:
        if all_targets:
            target_ledger.verify()
            process.update(startup_attempts=1, startup_status='reserved')
            journal.append('scorer_startup_reserved', {'panel_digest': panel.digest}); persist()
            try:
                service = scorer_factory(panel)
                if type(service) is not CombinationScorerProcessClient or service.joint_train is not True or service.panel != panel:
                    raise ContractError('exact closed C5 common independent scorer process required')
                service.assert_configuration(config=ScorerConfig(R(plan.protocol.record.data()['scorer'])),
                                             task_handle_bindings=plan.data()['scorer_handle_bindings'],
                                             execution_authority_keys={execution_authority.authority_id: execution_authority.key},
                                             scorer_authority_keys=scorer_authority_keys)
                process['startup_status'] = 'ready'
            except Exception as exc:
                process.update(startup_status='failed', error=type(exc).__name__ + ': ' + str(exc))
                for row in rows:
                    if row['status'] == 'succeeded': row.update(execution_status='succeeded', status='scoring_blocked', reason='scorer_startup')
            journal.append('scorer_startup_completed', {'status': process['startup_status'], 'error': process['error']}); persist()
            if process['startup_status'] == 'ready':
                for index, row in enumerate(rows):
                    result = targets[index]
                    if result is None or row['status'] != 'succeeded': continue
                    try:
                        _verify_target(result, barrier=barrier, panel=panel, ledger=target_ledger)
                    except ContractError as exc:
                        scorer_provider_terminal = True
                        row.update(execution_status='succeeded', status='scoring_ineligible', reason='scorer_provider_replay: ' + type(exc).__name__)
                        for later in rows[index + 1:]:
                            if later['status'] == 'succeeded': later.update(execution_status='succeeded', status='blocked', reason='scorer_provider_terminal')
                        journal.append('scorer_provider_terminal', {'arm_id': row['arm_id'], 'task_digest': row['task_digest'], 'error_type': type(exc).__name__})
                        persist(); break
                    recipe = next(recipe for recipe in plan.recipes if recipe['id'] == row['arm_id'])
                    packet = next(packet for packet in plan.packets if packet.task.content_hash == row['task_digest'])
                    try:
                        # _verify_target above is the C5-owned complete replay.
                        # The common serializer then has no authority of its own.
                        score_input = execution_authority.issue(_score_input_payload(panel, result.inner).data())
                        row['scorer_calls'] = 1
                        journal.append('scorer_reserved', {'arm_id': row['arm_id'], 'task_digest': row['task_digest'], 'input_digest': score_input.content_hash})
                        score = service.score_combination(panel=panel, cell=result.inner.cell, score_input=score_input)
                        verify_combination_adapted_receipt(score, authority_keys=scorer_authority_keys, config=service.config,
                                                           panel=panel, cell=result.inner.cell, score_input=score_input,
                                                           execution_authority_keys={execution_authority.authority_id: execution_authority.key})
                        score_inputs.append(score_input); scores.append(score)
                        row.update(status='scored', score=score.receipt.data())
                    except Exception as exc:
                        row.update(status='failed', reason=type(exc).__name__ + ': ' + str(exc))
                    journal.append('scorer_completed', {'arm_id': row['arm_id'], 'task_digest': row['task_digest'], 'status': row['status']}); persist()
    finally:
        if service is not None:
            process['close_attempts'] = 1
            try:
                service.close(); process['closed'] = service.process.poll() is not None
            except Exception as exc:
                process.update(closed=False, close_error=type(exc).__name__ + ': ' + str(exc))
            journal.append('scorer_closed', {'closed': process['closed']}); persist()

    # Capture every report input before this final fresh provenance check.  The
    # receipt below uses only captured values and cannot refresh originals.
    accounting = _native_accounting(executor)
    actual = _actual(tuple([*builds, *[target for target in targets if target is not None]]), accounting, rows)
    persist(accounting)
    final_provider_eligible = type(target_ledger) is PhaseProviderLedger and not scorer_provider_terminal
    if final_provider_eligible:
        try:
            # Recheck complete current stage provenance first.  The ledger verify
            # is deliberately the final original-provider read in this controller.
            for build in barrier.builds: executor.verify(build)
            for target in targets:
                if target is not None: _verify_target(target, barrier=barrier, panel=panel, ledger=target_ledger)
            target_ledger.verify()
        except ContractError as exc:
            final_provider_eligible = False
            journal.append('final_provider_replay_failed', {'error_type': type(exc).__name__})
    if not final_provider_eligible:
        for row in rows:
            if row['status'] == 'scored': row.update(execution_status='scored', status='scoring_ineligible', reason='final_provider_replay')
    receipt = R({'schema': _SCHEMA, 'plan_digest': plan.record.content_hash, 'allocation': plan.protocol.record.data()['allocation'],
                 'actual': actual, 'unused': {key: (None if value is None else plan.protocol.record.data()['allocation'][key] - value)
                                                for key, value in actual.items()}, 'builds': build_rows, 'targets': rows,
                 'barrier_digest': None if barrier is None else barrier.record.content_hash,
                 'panel_digest': None if panel is None else panel.digest,
                 'target_provider_ledger_digest': target_ledger.record.content_hash,
                 'target_provider_ledger_kind': type(target_ledger).__name__, 'native_accounting': accounting,
                 'historical_scorer_calls': len(scores), 'final_provider_eligible': final_provider_eligible,
                 'scorer_process': process, 'selection_opened': False, 'validation_opened': False,
                 'candidate_activation': 'none_offline_experiment', 'scientific_effectiveness_proven': False,
                 'status': 'complete_train_engineering' if (len(scores) == len(rows) and process['closed'] is True and final_provider_eligible) else 'inconclusive'})
    _exclusive(root / 'common-controller-receipt.json', receipt)
    return JointCommonTrainRun(root, plan, executor, barrier, panel, tuple(builds), tuple(targets), target_ledger,
                               tuple(score_inputs), tuple(scores), receipt)


def verify_joint_common_train_run(run: JointCommonTrainRun, *, execution_authority_keys: dict[str, bytes],
                                  scorer_authority_keys: dict[str, bytes]) -> FrozenRecord:
    """Freshly replay a complete controller output for a later TRAIN selector."""
    if type(run) is not JointCommonTrainRun or type(run.plan) is not FrozenJointTrainRuntimePlan:
        raise ContractError('exact common controller output required')
    allocation = run.plan.protocol.record.data()['allocation']
    expected_target_count = len(run.plan.recipes) * len(run.plan.packets)
    if (run.barrier is None or run.panel is None or type(run.target_ledger) is not PhaseProviderLedger
            or len(run.builds) != len(run.plan.builds) or len(run.targets) != expected_target_count
            or len(run.scores) != expected_target_count or len(run.score_inputs) != expected_target_count
            or len(run.panel.cells) != expected_target_count
            or allocation['unique_canonical_builds'] != len(run.plan.builds)
            or allocation['target_cells'] != expected_target_count):
        raise ContractError('only a complete common TRAIN output can feed a later selector')
    if (run.root / 'common-controller-receipt.json').read_bytes() != run.receipt.encoded.encode('utf-8'):
        raise ContractError('common controller receipt bytes changed')
    run.plan.__post_init__(); run.barrier.verify(); panel, scenarios = compile_panel(run.barrier)
    if panel != run.panel:
        raise ContractError('common controller panel differs from sealed barrier')
    if (run.barrier.executor is not run.executor or run.executor.plan is not run.plan
            or run.root != run.executor.root or run.builds != run.barrier.builds
            or tuple(run.executor.stages) != run.builds + run.targets):
        raise ContractError('common run does not own its exact original stage sequence')
    body = run.receipt.data()
    required = {'schema', 'plan_digest', 'allocation', 'actual', 'unused', 'builds', 'targets', 'barrier_digest', 'panel_digest',
                'target_provider_ledger_digest', 'target_provider_ledger_kind', 'native_accounting', 'historical_scorer_calls',
                'final_provider_eligible', 'scorer_process', 'selection_opened', 'validation_opened', 'candidate_activation',
                'scientific_effectiveness_proven', 'status'}
    if set(body) != required or body['schema'] != _SCHEMA or body['plan_digest'] != run.plan.record.content_hash or body['allocation'] != allocation:
        raise ContractError('common controller final receipt schema or plan binding differs')
    rows = body['targets']
    expected_cells = tuple(target.inner.cell for target in run.targets if target is not None)
    if (len(rows) != len(run.targets) or len(expected_cells) != expected_target_count or tuple(run.panel.cells) != expected_cells
            or tuple((row['arm_id'], row['task_digest']) for row in rows) != tuple((cell.arm_id, cell.task_digest) for cell in run.panel.cells)
            or any(row['status'] != 'scored' for row in rows)):
        raise ContractError('common controller does not retain a complete scored denominator')
    inputs = {tuple(score_input.data()['body']['cell_key']): score_input for score_input in run.score_inputs}
    scores = {score.cell_key: score for score in run.scores}
    keys = {cell.key for cell in run.panel.cells}
    if len(inputs) != len(run.score_inputs) or len(scores) != len(run.scores) or set(inputs) != keys or set(scores) != keys:
        raise ContractError('common controller score envelopes do not exactly cover the panel')
    expected_builds = [{'build_id': history_build_id(run.plan.protocol, recipe), 'recipe_id': recipe['id'],
                       'status': 'succeeded', 'receipt_digest': build.record.content_hash}
                      for recipe, build in zip(run.plan.builds, run.builds, strict=True)]
    expected_rows = [{'arm_id': target.inner.cell.arm_id, 'task_digest': target.inner.cell.task_digest,
                     'status': 'scored', 'scorer_calls': 1, 'receipt_digest': target.record.content_hash,
                     'score': scores[target.inner.cell.key].receipt.data()} for target in run.targets]
    if body['builds'] != expected_builds or rows != expected_rows:
        raise ContractError('common controller rows differ from original builds, targets or scores')
    process = body['scorer_process']
    if process != {'startup_attempts': 1, 'startup_status': 'ready', 'close_attempts': 1,
                   'closed': True, 'error': None}:
        raise ContractError('common controller scorer did not close successfully')
    calls = tuple(R(row['view']) for row in run.target_ledger.original.record.data()['calls'])
    accounting = call_accounting(calls)
    actual = _actual(tuple([*run.builds, *[target for target in run.targets if target is not None]]), accounting, rows)
    if (body['native_accounting'] != accounting or body['actual'] != actual
            or body['unused'] != {key: allocation[key] - value for key, value in actual.items()}
            or body['barrier_digest'] != run.barrier.record.content_hash or body['panel_digest'] != run.panel.digest
            or body['target_provider_ledger_digest'] != run.target_ledger.record.content_hash
            or body['target_provider_ledger_kind'] != 'PhaseProviderLedger' or body['historical_scorer_calls'] != len(run.scores)
            or body['selection_opened'] is not False or body['validation_opened'] is not False
            or body['candidate_activation'] != 'none_offline_experiment' or body['scientific_effectiveness_proven'] is not False):
        raise ContractError('common controller final receipt cross-binding differs')
    # This entire final pass is synchronous and read-only.  One fresh barrier
    # replay serves its 118 target replays; each target still checks its own
    # original files, trace, provider scope, score input, and score receipt.
    with _barrier_validation_scope(run.barrier) as context:
        for target, row in zip(run.targets, rows, strict=True):
            if target is None or target.inner.cell.key not in inputs or target.inner.cell.key not in scores:
                raise ContractError('common controller score binding is incomplete')
            _verify_target_in_context(target, barrier=run.barrier, panel=run.panel, ledger=run.target_ledger, context=context)
            score_input = inputs[target.inner.cell.key]
            signed = verify_combination_score_input(score_input, authority_keys=execution_authority_keys, panel=run.panel, cell=target.inner.cell)
            rebuilt = _score_input_payload(run.panel, target.inner)
            if {key: value for key, value in signed.data().items() if key != 'authority'} != rebuilt.data():
                raise ContractError('signed common score input differs from its replayed target candidate')
            verify_combination_adapted_receipt(scores[target.inner.cell.key], authority_keys=scorer_authority_keys,
                                               config=ScorerConfig(R(run.plan.protocol.record.data()['scorer'])), panel=run.panel,
                                               cell=target.inner.cell, score_input=score_input,
                                               execution_authority_keys=execution_authority_keys)
        run.target_ledger.verify()
    if body['final_provider_eligible'] is not True or body['status'] != 'complete_train_engineering':
        raise ContractError('common controller output is not currently provenance eligible')
    return run.receipt
