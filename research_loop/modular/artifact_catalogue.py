"""Strict append-only provenance journals; they do not replace source journals."""
from __future__ import annotations
import hashlib, math, os
from pathlib import Path
from typing import Any, Iterable, Mapping
from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.ontology import ContractError

STATUSES=frozenset({"produced","not_applied","failed","rejected","withdrawn","superseded","blocked"})
MODULES=frozenset({'P0', *(f'M{i}' for i in range(1,10))})
def source_snapshot(path: Path) -> dict[str, Any]:
    raw=path.resolve().read_bytes();return {"path":str(path.resolve()),"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)}

class ArtifactCatalogue:
    def __init__(self,path:Path,*,identity:DataIdentity,run_id:str|None,experiment_id:str|None,lock_digest:str|None,producer_source:Mapping[str,Any]|None=None):
        if type(identity) is not DataIdentity: raise ContractError("exact artifact identity required")
        identity.__post_init__()
        self.path,self.identity=Path(path),identity
        self.seal_path=self.path.with_name(self.path.name+'.seal.json')
        self.binding={"run_id":run_id,"experiment_id":experiment_id,"lock_digest":lock_digest}
        for value in self.binding.values():
            if value is not None: required_text(value,'artifact binding')
        self.producer_source=dict(producer_source or {});self._entries=[]
        self.verify()
    @classmethod
    def external(cls,path:Path,*,identity:DataIdentity,experiment_id:str|None=None,producer_source:Mapping[str,Any]|None=None):
        return cls(path,identity=identity,run_id=None,experiment_id=experiment_id,lock_digest=None,producer_source=producer_source)
    def _read(self):
        if not self.path.exists():return []
        raw=self.path.read_bytes()
        if raw and not raw.endswith(b'\n'): raise ContractError('incomplete catalogue journal write')
        rows=[]
        for line in raw.decode('utf-8').splitlines():
            if not line:raise ContractError("blank catalogue journal row")
            rows.append(FrozenRecord(line))
        return rows
    def records(self):
        self.verify();return tuple(FrozenRecord.from_dict(e.data()["descriptor"]) for e in self._entries)
    def _verify_source(self,source,cache=None):
        if set(source)!={"path","sha256","bytes"}:raise ContractError("producer source requires an actual file snapshot")
        key=(source["path"],source["sha256"],source["bytes"])
        if cache is not None and key in cache:return
        try:actual=source_snapshot(Path(source["path"]))
        except OSError as exc:raise ContractError("producer source is no longer resolvable") from exc
        if actual!=dict(source):raise ContractError("producer source drift")
        if cache is not None:cache.add(key)
    def _verify_refs(self,refs):
        if type(refs) is not list: raise ContractError('artifact references must be a list')
        for ref in refs:
            if not isinstance(ref,Mapping) or set(ref)!={"kind","digest","canonical"} or not isinstance(ref["kind"],str) or not isinstance(ref["digest"],str) or FrozenRecord.from_dict(ref["canonical"]).content_hash!=ref["digest"]:raise ContractError("reference is not resolvable canonical data")
            required_text(ref['kind'],'reference kind')
    def _validate_descriptor(self,body,seen,source_cache):
        """One validator for new entries and every subsequent disk read."""
        required={"schema","kind","module","coverage","identity","binding","payload","parents","control_sources","status","cost","checks","producer_source","config_refs","optimizer_visible","scientific_validated"}
        if type(body) is not dict or set(body)!=required or body['schema']!='artifact-descriptor-v2':
            raise ContractError('catalogue descriptor schema is invalid')
        required_text(body['kind'],'artifact kind')
        if (type(body['status']) is not str or body['status'] not in STATUSES
                or body['module'] is not None and (type(body['module']) is not str or body['module'] not in MODULES)
                or type(body['coverage']) is not str or body['coverage'] not in {'covered','uncovered'}
                or (body['coverage']=='uncovered') != (body['module'] is None)):
            raise ContractError('catalogue descriptor fields are invalid')
        if type(body['optimizer_visible']) is not bool or body['scientific_validated'] is not False:
            raise ContractError('catalogue validation flags are invalid')
        if self.identity.domain=='validation' and body['optimizer_visible']:
            raise ContractError('validation artifacts cannot enter optimizer context')
        if body['identity']!=self.identity.data() or body['binding']!=self.binding:
            raise ContractError('catalogue identity, domain or run binding differs')
        parents=body['parents']
        if (type(parents) is not list or any(type(p) is not str for p in parents)
                or len(set(parents))!=len(parents) or any(p not in seen for p in parents)):
            raise ContractError('artifact parent is missing, duplicated or unordered')
        if body['control_sources']!=[]:
            raise ContractError('external control sources need authenticated typed edges')
        payload=body['payload']
        if type(payload) is not dict or set(payload)!={'digest','bytes','encoding','canonical'}:
            raise ContractError('payload schema is invalid')
        if payload['canonical'] is None:
            expected={'digest':None,'bytes':None,'encoding':'absent','canonical':None}
        else:
            if type(payload['canonical']) is not dict: raise ContractError('payload must be a canonical object')
            frozen=FrozenRecord.from_dict(payload['canonical'])
            expected={'digest':frozen.content_hash,'bytes':len(frozen.encoded.encode('utf-8')),'encoding':'canonical_json','canonical':frozen.data()}
        if payload!=expected: raise ContractError('payload content or digest drift')
        cost=body['cost']
        if type(cost) is not dict or set(cost)!={'known','units'} or type(cost['known']) is not bool:
            raise ContractError('artifact cost must preserve known versus unknown')
        units=cost['units']
        if (not cost['known'] and units is not None or cost['known'] and
                (type(units) not in (int,float) or not math.isfinite(units) or units<0)):
            raise ContractError('artifact cost units are invalid')
        self._verify_source(body['producer_source'],source_cache)
        self._verify_refs(body['config_refs']);self._verify_refs(body['checks'])
    def append(self,*,kind,module,payload,parents:Iterable[str]=(),control_sources:Iterable[FrozenRecord]=(),status="produced",producer_source=None,config_refs:Iterable[Mapping[str,Any]]=(),cost=None,checks:Iterable[Mapping[str,Any]]=(),optimizer_visible=False,coverage="covered"):
        self.verify()
        if self.seal_path.exists(): raise ContractError('sealed catalogue cannot accept another artifact')
        if status not in STATUSES:raise ContractError("artifact status is not recognized")
        if module is not None and module not in MODULES:raise ContractError("artifact module must be P0 or M1 through M9 or explicitly uncovered")
        if coverage not in {"covered","uncovered"} or (coverage=="uncovered") != (module is None):raise ContractError("unknown module/event must be explicitly uncovered")
        if self.identity.domain=="validation" and optimizer_visible:raise ContractError("validation artifacts cannot enter optimizer context")
        known={e.data()['descriptor_digest']:FrozenRecord.from_dict(e.data()['descriptor']) for e in self._entries};parents=list(parents)
        if len(set(parents))!=len(parents) or any(p not in known for p in parents):raise ContractError("artifact parent is missing from this immutable catalogue")
        if any(known[p].data()["identity"]!=self.identity.data() for p in parents):raise ContractError("cross-subject or cross-domain artifact parent")
        if tuple(control_sources):
            raise ContractError("cross-subject TRAIN control sources are unsupported until sealed external edges exist")
        controls=[]
        if payload is None:payload_body={"digest":None,"bytes":None,"encoding":"absent","canonical":None}
        else:
            frozen=payload if isinstance(payload,FrozenRecord) else FrozenRecord.from_dict(payload);payload_body={"digest":frozen.content_hash,"bytes":len(frozen.encoded.encode()),"encoding":"canonical_json","canonical":frozen.data()}
        cost={"known":False,"units":None} if cost is None else dict(cost)
        if set(cost)!={"known","units"} or type(cost["known"]) is not bool or not cost["known"] and cost["units"] is not None:raise ContractError("artifact cost must preserve known versus unknown")
        source=dict(producer_source or self.producer_source);self._verify_source(source);refs=list(config_refs);checks=list(checks);self._verify_refs(refs);self._verify_refs(checks)
        d=FrozenRecord.from_dict({"schema":"artifact-descriptor-v2","kind":required_text(kind,"artifact kind"),"module":module,"coverage":coverage,"identity":self.identity.data(),"binding":self.binding,"payload":payload_body,"parents":parents,"control_sources":controls,"status":status,"cost":cost,"checks":checks,"producer_source":source,"config_refs":refs,"optimizer_visible":optimizer_visible,"scientific_validated":False})
        self._validate_descriptor(d.data(),set(known),set())
        if d.content_hash in known:raise ContractError("catalogue is append-only; duplicate descriptor")
        entry=FrozenRecord.from_dict({"schema":"artifact-catalogue-entry-v2","sequence":len(self._entries),"previous":self._entries[-1].content_hash if self._entries else None,"descriptor_digest":d.content_hash,"descriptor":d.data()})
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open("a",encoding="utf-8",newline="\n") as f:f.write(entry.encoded+"\n");f.flush();os.fsync(f.fileno())
        self._entries.append(entry);return d
    def seal(self):
        self.verify()
        record=FrozenRecord.from_dict({"schema":"artifact-catalogue-seal-v1","count":len(self._entries),"head":self._entries[-1].content_hash if self._entries else None,"binding":self.binding})
        if not self.seal_path.exists():
            self.seal_path.parent.mkdir(parents=True,exist_ok=True)
            with self.seal_path.open('x',encoding='utf-8',newline='\n') as stream:
                stream.write(record.encoded+'\n');stream.flush();os.fsync(stream.fileno())
        return record
    def verify(self,seal:FrozenRecord|None=None):
        entries=self._read();previous=None;seen=set();source_cache=set()
        for n,e in enumerate(entries):
            row=e.data()
            if set(row)!={"schema","sequence","previous","descriptor_digest","descriptor"} or row["schema"]!="artifact-catalogue-entry-v2" or type(row['sequence']) is not int or row["sequence"]!=n or row["previous"]!=previous:raise ContractError("catalogue journal chain is tampered")
            d=FrozenRecord.from_dict(row["descriptor"]);body=d.data()
            if row["descriptor_digest"]!=d.content_hash or d.content_hash in seen or body.get("schema")!="artifact-descriptor-v2":raise ContractError("catalogue descriptor is tampered or duplicated")
            self._validate_descriptor(body,seen,source_cache)
            previous=e.content_hash;seen.add(d.content_hash)
        self._entries=entries
        expected=FrozenRecord.from_dict({"schema":"artifact-catalogue-seal-v1","count":len(entries),"head":previous,"binding":self.binding})
        if self.seal_path.exists() and self.seal_path.read_bytes()!=(expected.encoded+'\n').encode('utf-8'):
            raise ContractError('catalogue seal does not bind current journal')
        if seal is not None and (type(seal) is not FrozenRecord or seal!=expected):raise ContractError("catalogue seal does not bind current journal")
