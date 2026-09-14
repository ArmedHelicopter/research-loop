import pytest
from evaluation.modular.legacy_primary_packet_artifacts import write, verify
from research_loop.modular.contracts import DataIdentity, PublicTask
from research_loop.ontology import ContractError

def test_primary_packet_is_train_bound_and_tamper_refused(tmp_path):
    task=PublicTask.create(DataIdentity('synthetic','item','group','v1','split','train'),{'question':'public'})
    anchor={'source_group':'group','official_split':'train','split_digest':'a'*64,'csv_source_sha256':'b'*64}
    root=tmp_path/'packet';write(root,task,anchor,b'x\n',b'{}')
    assert verify(root,task,anchor).data()['schema']=='legacy-primary-train-packet-v1'
    (root/'data.csv').write_bytes(b'changed')
    with pytest.raises(ContractError):verify(root,task,anchor)
    with pytest.raises(ContractError):write(tmp_path/'val',PublicTask.create(DataIdentity('x','y','z','v','s','validation'),{}),anchor,b'',b'')
