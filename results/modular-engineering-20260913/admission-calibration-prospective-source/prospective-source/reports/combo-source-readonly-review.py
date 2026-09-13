"""Synthetic packet forgery checks; target checkout is never written."""
import sys
sys.path.insert(0,'E:/_ryanDev/AI/research-loop-modular/combo-export')
sys.path.insert(0,'E:/_ryanDev/AI/research-loop-modular/combo-export/tests')
from dataclasses import replace
import pytest
from test_combination_prospective_train_source import prepare
from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError, canonical

@pytest.mark.parametrize('kind',['m4','lineage','retrieval'])
@pytest.mark.parametrize('field,value',[('csv_byte_count',-1),('input_bindings_digest','0'*64),('eligibility_sha256','0'*64)])
def test_serialized_receipt_false_source_metadata_is_rejected(tmp_path,kind,field,value):
    setup=prepare(tmp_path,kind);packet,other=setup['packets']
    receipt=FrozenRecord.from_dict({**packet.receipt.data(),field:value})
    packet.packet_path.write_text(canonical({'task':packet.task.data(),'receipt':receipt.data()}),encoding='utf-8')
    altered=replace(packet,receipt=receipt)
    with pytest.raises(ContractError):setup['compile_fn'](setup['config'],(altered,other))
