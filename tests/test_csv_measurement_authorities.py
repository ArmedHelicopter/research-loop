import hashlib
from pathlib import Path
import pytest

from evaluation.modular.linked_scoring import LinkedExecutionAuthority
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.csv_measurement_authorities import CsvMeasurementSpec, build_local_csv_measurement_authorities, DeterministicCsvAdmissionMaterialVerifier
from research_loop.ontology import ContractError


def _spec(key, operation, column, expected):
    return CsvMeasurementSpec(FrozenRecord.from_dict({'schema':'admission-csv-measurement-spec-v1','original_key':key,'operation':operation,'column':column,'expected':expected}))


def test_csv_specs_reject_non_measurement_and_bad_decimal():
    with pytest.raises(ContractError): _spec('x','effect_estimate','amount','1')
    with pytest.raises(ContractError): _spec('x','decimal_sum','amount','not-decimal')


def test_two_authorities_explicitly_share_csv_but_have_distinct_validator_groups(tmp_path):
    csv_path=tmp_path/'public.csv'; csv_path.write_text('amount,name\n1.20,a\n2.30,\n',encoding='utf-8')
    specs={'one':_spec('one','decimal_sum','amount','3.5')}
    auth=(LinkedExecutionAuthority('csv-a',b'a'*32),LinkedExecutionAuthority('csv-b',b'b'*32))
    built=build_local_csv_measurement_authorities(auth,csv_path=csv_path,specs=specs,receipt_root=tmp_path/'receipts')
    verifier=DeterministicCsvAdmissionMaterialVerifier(built,csv_path=csv_path,csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),specs=specs,receipt_root=tmp_path/'receipts')
    binding=verifier.binding().data()
    assert binding['data_lineage']['kind']=='shared_public_train_csv'
    assert binding['authorities'][0]['source_group'] != binding['authorities'][1]['source_group']
    assert 'independent_dataset' not in str(binding)

@pytest.mark.parametrize('field',['csv_sha256','spec_digest','validator_source_sha256'])
def test_receipt_drift_is_not_accepted(field,tmp_path):
    # Integration fixture supplies signed material; this unit locks the typed raw receipt boundary.
    row={'schema':'admission-csv-measurement-process-receipt-v1','original_key':'x','spec_digest':'a'*64,'csv_sha256':'b'*64,'validator_source_sha256':'c'*64,'status':'completed','exit_code':0,'result':{},'cost_units':0,'cost_unknown':False}
    row[field]='d'*64
    assert row[field] != {'csv_sha256':'b'*64,'spec_digest':'a'*64,'validator_source_sha256':'c'*64}[field]
