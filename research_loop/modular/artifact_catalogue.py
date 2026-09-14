"""Strict append-only provenance journals; they do not replace source journals."""
from __future__ import annotations
import hashlib, os
from pathlib import Path
from typing import Any, Iterable, Mapping
from research_loop.modular.contracts import DataIdentity, FrozenRecord, required_text
from research_loop.ontology import ContractError

STATUSES=frozenset({"produced","not_applied","failed","rejected","withdrawn","superseded","blocked"})
def source_snapshot(path: Path) -> dict[str, Any]:
    raw=path.resolve().read_bytes();return {"path":str(path.resolve()),"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)}

class ArtifactCatalogue:
    def __init__(self,path:Path,*,identity:DataIdentity,run_id:str|None,experiment_id:str|None,lock_digest:str|None,producer_source:Mapping[str,Any]|None=None):
        self.path,self.identity=path,identity;self.binding={"run_id":run_id,"experiment_id":experiment_id,"lock_digest":lock_digest};self.producer_source=dict(producer_source or {});self._entries=self._read()
    @classmethod
    def external(cls,path:Path,*,identity:DataIdentity,experiment_id:str|None=None,producer_source:Mapping[str,Any]|None=None):
        return cls(path,identity=identity,run_id=None,experiment_id=experiment_id,lock_digest=None,producer_source=producer_source)
    def _read(self):
        if not self.path.exists():return []
        rows=[]
        for line in self.path.read_text(encoding="utf-8").splitlines():
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
        for ref in refs:
            if not isinstance(ref,Mapping) or set(ref)!={"kind","digest","canonical"} or not isinstance(ref["kind"],str) or not isinstance(ref["digest"],str) or FrozenRecord.from_dict(ref["canonical"]).content_hash!=ref["digest"]:raise ContractError("reference is not resolvable canonical data")
    def append(self,*,kind,module,payload,parents:Iterable[str]=(),control_sources:Iterable[FrozenRecord]=(),status="produced",producer_source=None,config_refs:Iterable[Mapping[str,Any]]=(),cost=None,checks:Iterable[Mapping[str,Any]]=(),optimizer_visible=False,coverage="covered"):
        self.verify()
        if status not in STATUSES:raise ContractError("artifact status is not recognized")
        if module is not None and module not in {f"M{i}" for i in range(1,10)}:raise ContractError("artifact module must be M1 through M9 or explicitly uncovered")
        if coverage not in {"covered","uncovered"} or coverage=="uncovered" and module is not None:raise ContractError("unknown module/event must be explicitly uncovered")
        if self.identity.domain=="validation" and optimizer_visible:raise ContractError("validation artifacts cannot enter optimizer context")
        known={r.content_hash:r for r in self.records()};parents=list(parents)
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
        if d.content_hash in known:raise ContractError("catalogue is append-only; duplicate descriptor")
        entry=FrozenRecord.from_dict({"schema":"artifact-catalogue-entry-v2","sequence":len(self._entries),"previous":self._entries[-1].content_hash if self._entries else None,"descriptor_digest":d.content_hash,"descriptor":d.data()})
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open("a",encoding="utf-8",newline="\n") as f:f.write(entry.encoded+"\n");f.flush();os.fsync(f.fileno())
        self._entries.append(entry);return d
    def seal(self):
        self.verify();return FrozenRecord.from_dict({"schema":"artifact-catalogue-seal-v1","count":len(self._entries),"head":self._entries[-1].content_hash if self._entries else None,"binding":self.binding})
    def verify(self,seal:FrozenRecord|None=None):
        entries=self._read();previous=None;seen=set();source_cache=set()
        for n,e in enumerate(entries):
            row=e.data()
            if set(row)!={"schema","sequence","previous","descriptor_digest","descriptor"} or row["schema"]!="artifact-catalogue-entry-v2" or row["sequence"]!=n or row["previous"]!=previous:raise ContractError("catalogue journal chain is tampered")
            d=FrozenRecord.from_dict(row["descriptor"]);body=d.data()
            if row["descriptor_digest"]!=d.content_hash or d.content_hash in seen or body.get("schema")!="artifact-descriptor-v2":raise ContractError("catalogue descriptor is tampered or duplicated")
            required={"schema","kind","module","coverage","identity","binding","payload","parents","control_sources","status","cost","checks","producer_source","config_refs","optimizer_visible","scientific_validated"}
            if set(body)!=required or body["status"] not in STATUSES or body["module"] is not None and body["module"] not in {f"M{i}" for i in range(1,10)} or body["coverage"] not in {"covered","uncovered"} or body["coverage"]=="uncovered" and body["module"] is not None or type(body["optimizer_visible"]) is not bool or body["scientific_validated"] is not False or body["control_sources"]:raise ContractError("catalogue descriptor fields are invalid")
            if body["identity"]!=self.identity.data() or body["binding"]!=self.binding or any(p not in seen for p in body["parents"]):raise ContractError("catalogue lineage is tampered or unordered")
            p=body["payload"]
            if p["canonical"] is None:
                if p!={"digest":None,"bytes":None,"encoding":"absent","canonical":None}:raise ContractError("absent payload is inconsistent")
            else:
                frozen=FrozenRecord.from_dict(p["canonical"])
                if p!={"digest":frozen.content_hash,"bytes":len(frozen.encoded.encode()),"encoding":"canonical_json","canonical":frozen.data()}:raise ContractError("payload content or digest drift")
            cost=body["cost"]
            if set(cost)!={"known","units"} or type(cost["known"]) is not bool or not cost["known"] and cost["units"] is not None:raise ContractError("catalogue cost is invalid")
            self._verify_source(body["producer_source"],source_cache);self._verify_refs(body["config_refs"]);self._verify_refs(body["checks"]);previous=e.content_hash;seen.add(d.content_hash)
        self._entries=entries
        if seal is not None and seal.data()!={"schema":"artifact-catalogue-seal-v1","count":len(entries),"head":previous,"binding":self.binding}:raise ContractError("catalogue seal does not bind current journal")
