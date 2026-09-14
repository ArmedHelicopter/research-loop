"""Rank the complete authenticated common TRAIN run under its precommit.

An offline choice identifies the whole recipe, not just its learned package:
different module activations can share the same history package. Nothing here
opens validation, grants deployment or completes the original Q/C studies.
"""
from dataclasses import dataclass
import math

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.joint_deployment import JointComponentVersion
from research_loop.modular.joint_train_panel import JointTrainPanel, history_build_id
from research_loop.modular.train_selection import FrozenTrainSelectionRule, _selection
from research_loop.ontology import ContractError

R = FrozenRecord.from_dict


@dataclass(frozen=True)
class _MatchedCells:
    cells: tuple
    required_benchmarks: tuple


def _rank(panel, metrics):
    """Arithmetic only; callers cannot use this as execution authentication."""
    if type(panel) is not JointTrainPanel:
        raise ContractError('exact common TRAIN panel required')
    panel.__post_init__()
    policy = FrozenTrainSelectionRule(R(panel.protocol.record.data()['selection_rule'])).record.data()
    if set(metrics) != {cell.key for cell in panel.cells}:
        raise ContractError('complete common score denominator required, including B0')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in metrics.values()):
        raise ContractError('common training metrics must be finite unit scores')
    matched = tuple(cell for cell in panel.cells if cell.arm_id != 'B0')
    if {cell.arm_id for cell in matched} != set(policy['tie_break_order']):
        raise ContractError('precommitted matched recipe inventory differs')
    packages = {}
    for cell in matched:
        if cell.arm_id in packages and packages[cell.arm_id] != cell.package_digest:
            raise ContractError('one recipe must bind one history package across targets')
        packages[cell.arm_id] = cell.package_digest
    # Preserve the existing paired-cell -> group -> benchmark estimator and
    # frozen tie order. B0 remains in the authenticated denominator, not ranking.
    return _selection(_MatchedCells(matched, panel.required_benchmarks), policy, metrics, packages)


def select_joint_common_train(run, *, execution_authority_keys, scorer_authority_keys):
    """Reverify a whole controller run, then compute its reproducible choice.

    The controller owns original traces, actual Docker/builds and signed score
    inputs. Its full verifier is called once at this boundary. Pure arithmetic
    below uses immutable verified records and does not dispatch any operation.
    """
    from research_loop.modular.joint_train_controller import (
        JointCommonTrainRun, verify_joint_common_train_run)

    if type(run) is not JointCommonTrainRun:
        raise ContractError('original complete common TRAIN controller run required')
    checked = verify_joint_common_train_run(run,
        execution_authority_keys=execution_authority_keys,
        scorer_authority_keys=scorer_authority_keys)
    if type(checked) is not FrozenRecord or checked != run.receipt:
        raise ContractError('common controller verification did not bind its final receipt')
    panel = run.panel
    if type(panel) is not JointTrainPanel or panel.protocol != run.plan.protocol:
        raise ContractError('common selection protocol differs from original runtime')
    metrics = {}
    score_rows = []
    for score in run.scores:
        if score.cell_key in metrics:
            raise ContractError('one score cannot count twice in common TRAIN selection')
        value = score.receipt.data()['body']['metric']['value']
        metrics[score.cell_key] = value
        score_rows.append({'cell_key': list(score.cell_key),
                           'receipt_digest': score.receipt.content_hash, 'value': value})
    ranked = _rank(panel, metrics)
    protocol = panel.protocol.record.data()
    recipe = next(row['recipe'] for row in protocol['catalogue']['recipes']
                  if row['recipe']['id'] == ranked['selected_arm'])
    build_id = history_build_id(panel.protocol, recipe)
    subject = R({'schema': 'c5-common-train-selected-subject-v1',
        'protocol_digest': panel.protocol.digest, 'runtime_plan_digest': run.plan.record.content_hash,
        'panel_digest': panel.digest, 'recipe': recipe,
        'history_build_id': build_id,
        'history_receipt_digest': panel.training_provenance.data()['build_receipts'][build_id],
        'package_digest': ranked['selected_package_digest'],
        'component_templates': {name: JointComponentVersion(R(value)).digest
                                for name, value in protocol['component_templates'].items()},
        'deployment_snapshot_complete': False})
    return R({'schema': 'c5-common-train-selection-v1',
        'controller_receipt_digest': checked.content_hash,
        'protocol_digest': panel.protocol.digest, 'panel_digest': panel.digest,
        'selection_rule': protocol['selection_rule'],
        'selection_rule_digest': R(protocol['selection_rule']).content_hash,
        'expected_cells': len(panel.cells), 'scored_cells': len(score_rows),
        'score_receipts': sorted(score_rows, key=lambda row: row['cell_key']),
        'b0_reference': [row for row in score_rows if row['cell_key'][-1] == 'B0'],
        'b0_used_for_selection': False, **ranked,
        'selected_subject': subject.data(), 'selected_subject_digest': subject.content_hash,
        'combination_candidates_retained': list(protocol['selection_rule']['tie_break_order']),
        'combination_pruning_authorized': False,
        'structural_origins_retained': protocol['catalogue']['structural_origins'],
        'original_issue_contracts_digest': R(protocol['issue_contracts']).content_hash,
        'original_experiments_completed': False, 'interaction_effect': 'not_estimated',
        'selection_scope': 'train_only', 'scientific_validity': 'not_measured',
        'acceptance_verified': False, 'validation_access_authorized': False,
        'deployment_authorized': False})


def verify_joint_common_selection(selection, *, run, execution_authority_keys, scorer_authority_keys):
    """Recompute from current original execution rather than trusting a choice."""
    if type(selection) is not FrozenRecord:
        raise ContractError('frozen common TRAIN choice required')
    expected = select_joint_common_train(run, execution_authority_keys=execution_authority_keys,
        scorer_authority_keys=scorer_authority_keys)
    if selection != expected:
        raise ContractError('common TRAIN selection differs from verified original run')
    return expected
