"""Versioned VAL-only execution material; existing TRAIN constructors stay closed.

These inputs describe a fixed diagnostic on one already leased task. No API
selects a strategy, changes a learned package or exports observations to TRAIN.
"""
from dataclasses import dataclass

from research_loop.modular.admission_combination import FrozenAdmissionMaterial, _validate_admission_record
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.csv_measurement_authorities import (
    CsvMeasurementAdmissionMaterialVerifier, _build_csv_measurement_admission_verifier,
)
from research_loop.modular.exploration_scheduler_combination import (
    _validate_phase_record, _run_phase_operations, verify_phase,
)
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.retrieval_panel_drivers import _docs, _select_sources
from research_loop.modular.retrieval_review_combination_driver import BUDGET, public_retrieval
from research_loop.ontology import ContractError

R = FrozenRecord.from_dict


class ValidationAdmissionMaterial(FrozenAdmissionMaterial):
    def __post_init__(self):
        _validate_admission_record(self.record, domain='validation', schema='validation-admission-material-v1')


class ValidationCsvMeasurementVerifier(CsvMeasurementAdmissionMaterialVerifier):
    material_type = ValidationAdmissionMaterial

    def _require_domain(self, request):
        ValidationAdmissionMaterial(R(request.data()['material']))
        if DataIdentity.parse(request.data()['material']['identity']).domain != 'validation':
            raise ContractError('validation measurement cannot accept TRAIN material')

    def binding(self):
        body = super().binding().data()
        body['domain_contract'] = 'fixed-validation-csv-measurement-v1'
        return R(body)


def build_validation_csv_verifier(*, authorities, datasets, receipt_root):
    return _build_csv_measurement_admission_verifier(authorities=authorities, datasets=datasets,
        receipt_root=receipt_root, verifier_type=ValidationCsvMeasurementVerifier)


@dataclass(frozen=True)
class ValidationPhaseMaterial:
    record: FrozenRecord

    def __post_init__(self):
        _validate_phase_record(self.record, domain='validation', schema='validation-phase-material-v1')

    def data(self):
        return self.record.data()


def run_validation_phase(*, material, cell, objective, root, broker, inputs, image,
                         timeout_seconds, selected_job_id, artifact_bridge=None):
    if (type(material) is not ValidationPhaseMaterial or type(objective) is not FrozenRecord
            or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120
            or not isinstance(broker, DockerExecutionBroker) or cell.identity.domain != 'validation'
            or material.data()['identity'] != cell.identity.data() or material.data()['task_digest'] != cell.task_digest):
        raise ContractError('exact validation phase material, cell and bounded execution required')
    material.__post_init__()
    if artifact_bridge is not None:
        from research_loop.modular.phase_artifacts import PhaseArtifactBridge
        if type(artifact_bridge) is not PhaseArtifactBridge:
            raise ContractError('typed validation phase artifact bridge required')
    result = _run_phase_operations(material=material, cell=cell, objective=objective, root=root, broker=broker,
        inputs=inputs, image=image, timeout_seconds=timeout_seconds, selected_job_id=selected_job_id,
        artifact_bridge=artifact_bridge)
    if result != verify_phase(material=material, cell=cell, objective=objective, root=root, image=image,
                              timeout_seconds=timeout_seconds, inputs=inputs, selected_job_id=selected_job_id):
        raise ContractError('validation phase original replay differs')
    return result


def freeze_validation_retrieval(task, sources, question):
    if (type(task) is not PublicTask or task.identity.domain != 'validation'
            or not isinstance(question, str) or not question.strip()):
        raise ContractError('fixed validation task and query required')
    originals, roots, public = _docs(sources), {}, []
    for index, doc in enumerate(originals):
        root = roots.setdefault(doc.root_source_id, f'r{len(roots)+1:03d}')
        public.append({**doc.data(), 'source_id': f's{index+1:03d}', 'root_source_id': root})
    return R({'schema': 'validation-retrieval-material-v1', 'identity': task.identity.data(),
              'task_digest': task.content_hash, 'sources': public, 'original_sources': [d.data() for d in originals],
              'query': {'task_digest': task.content_hash, 'question': question}, 'budget': BUDGET})


def validation_retrieval(session, task, material, provider, enabled):
    body = material.data()
    if freeze_validation_retrieval(task, body['original_sources'], body['query']['question']) != material:
        raise ContractError('validation corpus or query differs from its frozen projection')
    docs = _docs(body['sources'])
    # This records a binding, not a claim that public source prose is evidence.
    session._record('validation_retrieval_binding', {'material_digest': material.content_hash,
        'original_sources_digest': R({'sources': body['original_sources']}).content_hash})
    projection, usage = _select_sources(provider, session, docs, body['query'], BUDGET,
                                        'Q8.3', 'three_lane', enabled)
    session._record('retrieval_review_sources', {'projection': projection, 'usage': usage})
    return public_retrieval(projection)


@dataclass(frozen=True)
class ValidationBundleMaterial:
    admission: ValidationAdmissionMaterial
    phase: ValidationPhaseMaterial
    retrieval: FrozenRecord

    def __post_init__(self):
        if (type(self.admission) is not ValidationAdmissionMaterial or type(self.phase) is not ValidationPhaseMaterial
                or type(self.retrieval) is not FrozenRecord):
            raise ContractError('exact validation target materials required')
        self.admission.__post_init__(); self.phase.__post_init__()
        a, p, r = self.admission.data(), self.phase.data(), self.retrieval.data()
        if (any(a[key] != p[key] for key in ('identity', 'task_digest', 'public_artifacts', 'context_budget_bytes'))
                or any(a[key] != r.get(key) for key in ('identity', 'task_digest'))
                or r.get('schema') != 'validation-retrieval-material-v1'):
            raise ContractError('validation materials do not share exact task, input and context bindings')

    @property
    def record(self):
        return R({'schema': 'validation-bundle-material-v1', 'admission': self.admission.data(),
                  'phase': self.phase.data(), 'retrieval': self.retrieval.data()})
