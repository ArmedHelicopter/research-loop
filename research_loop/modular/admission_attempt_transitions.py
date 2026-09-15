"""Immutable controller-attempt checkpoint sidecar."""
import hashlib,json
from pathlib import Path
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.ontology import ContractError
class AttemptTransitions:
 def __init__(self,root):self.root=Path(root);self.path=self.root/'controller-attempt-transitions.jsonl';self.n=0;self.prev='0'*64
 def append(self,raw):
  row={'schema':'admission-controller-attempt-transition-v1','sequence':self.n+1,'previous':self.prev,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'producer_source':source_snapshot(Path(__file__))}
  rec=FrozenRecord.from_dict(row);self.path.open('a',encoding='utf8',newline='\n').write(rec.encoded+'\n');self.n+=1;self.prev=rec.content_hash
 def receipt(self):return FrozenRecord.from_dict({'schema':'admission-controller-attempt-transitions-v1','count':self.n,'tail':self.prev})
def verify(root,receipt):
 rows=[];prev='0'*64
 for line in (Path(root)/'controller-attempt-transitions.jsonl').read_text(encoding='utf8').splitlines():
  r=FrozenRecord(line).data()
  if r['sequence']!=len(rows)+1 or r['previous']!=prev or r['producer_source']!=source_snapshot(Path(__file__)):raise ContractError('attempt transition differs')
  prev=FrozenRecord(line).content_hash;rows.append(r)
 if receipt.data()!={'schema':'admission-controller-attempt-transitions-v1','count':len(rows),'tail':prev}:raise ContractError('attempt transition receipt differs')
 return receipt
