"""Public train-only improvement controllers; no validation acceptance authority.

Candidate training reuses the metaprogram phase's actual process, builder,
Docker, failure, source-binding and cost verifier rather than reimplementing it.
"""
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.metaprogram_training import (
    FrozenMetaTrainingPlan, FrozenMetaTarget, FrozenTrainHistory,
    metaprogram_schemas, model_configuration,
    run_metaprogram_training, verify_metaprogram_training)
from research_loop.modular.modules.improvement import FrozenBuilderVersion


def freeze_candidate_training(*, targets, histories, parent, fixed_builder,
                              manual_builder, baseline_digest, p0_control, image,
                              model_config, timeout_seconds=20):
    """Freeze Q6.2's complete fixed/manual/automatic by M9 train design.

    Manual is a caller-supplied predeclared change associated with the complete
    history whitelist. That association does not authenticate human authorship
    or establish that the caller derived the change from those observations.
    """
    histories=tuple(histories)
    source=FrozenRecord.from_dict({'history_bindings':[h.binding.content_hash for h in histories],
        'builder_digest':manual_builder.digest,'origin':'caller_frozen_manual_training'})
    return FrozenMetaTrainingPlan.freeze(targets=targets,histories=histories,parent=parent,
        fixed_builder=fixed_builder,manual_builder=manual_builder,manual_source=source,
        experiment_id='Q6.2',baseline_digest=baseline_digest,p0_control=p0_control,image=image,
        model_config=model_config,timeout_seconds=timeout_seconds)


def run_candidate_training(plan, **kwargs):
    from research_loop.ontology import ContractError
    if not isinstance(plan,FrozenMetaTrainingPlan) or plan.experiment_id!='Q6.2':
        raise ContractError('candidate controller requires the frozen Q6.2 phase')
    return run_metaprogram_training(plan,**kwargs)
