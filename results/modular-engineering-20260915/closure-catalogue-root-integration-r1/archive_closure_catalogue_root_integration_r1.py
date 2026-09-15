"""Prepare-only retention helper for the closed root closure/catalogue integration check."""
from __future__ import annotations
import hashlib, importlib.util, json, shutil, xml.etree.ElementTree as ET, zipfile
from pathlib import Path

BASE = Path(r"E:\_ryanDev\AI\research-loop-modular")
WORK = BASE / "work"
PREFIX = "closure-catalogue-root-integration-r1"
COMMIT = "a2eaafc3ee0e4a9eb219741d8e1c10422f0f6d2b"
DEST = BASE / "artifact-evidence-provenance" / "results" / "modular-engineering-20260915" / PREFIX
PRIVATE = BASE / "retained-private-evidence" / PREFIX
HELPER = WORK / "prepare_headless_lineage_full4_archive_r1.py"


def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_bytes())
def stamp(path):
    raw=path.read_bytes(); return {"sha256":sha(raw),"bytes":len(raw),"mtime_ns":path.stat().st_mtime_ns}
def write_new(path, value):
    with path.open("xb") as out: out.write((json.dumps(value,ensure_ascii=False,indent=2)+"\n").encode())
def retention():
    spec=importlib.util.spec_from_file_location("closure_catalogue_retention",HELPER)
    if spec is None or spec.loader is None: raise RuntimeError("retention helper is not loadable")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

def main():
    if DEST.exists() or PRIVATE.exists(): raise SystemExit("refusing to overwrite archive output")
    root=WORK/PREFIX
    if not root.is_dir(): raise SystemExit("closed run root is missing")
    before=read(WORK/(PREFIX+"-before.json")); closed=read(WORK/(PREFIX+"-closed.json")); members=read(WORK/(PREFIX+"-source-members.json"))
    started=read(WORK/(PREFIX+"-native-start.json")); completion=read(WORK/(PREFIX+"-native-completion.json"))
    if ("session_id" in started or started.get("exit_code")!=0 or completion.get("schema")!="native-command-completion-v1"
            or completion.get("result")!=started or completion.get("source_commit")!=COMMIT
            or before.get("commit")!=COMMIT or closed.get("commit")!=COMMIT or members.get("commit")!=COMMIT
            or closed.get("exit_code")!=0 or not closed.get("source_unchanged") or before.get("source_before")!=closed.get("source_after")
            or closed.get("source_count")!=799 or closed.get("new_paid_calls")!=0): raise SystemExit("closed command receipt differs")
    junit_path=WORK/(PREFIX+".xml"); log_path=WORK/(PREFIX+".log"); sourcezip=WORK/(PREFIX+"-sources.zip")
    if sha(junit_path.read_bytes())!=closed.get("report_sha256"): raise SystemExit("JUnit hash differs")
    suites=list(ET.parse(junit_path).getroot().iter("testsuite")); junit={k:sum(int(s.get(k,0)) for s in suites) for k in ("tests","failures","errors","skipped")}
    if junit!={"tests":33,"failures":0,"errors":0,"skipped":0} or closed.get("junit")!=junit: raise SystemExit("JUnit totals differ")
    if sha(sourcezip.read_bytes())!=members.get("archive_sha256") or before["source_before"]!={r["path"]:r["sha256"] for r in members["members"]}: raise SystemExit("source archive binding differs")
    with zipfile.ZipFile(sourcezip) as archive:
        if archive.testzip() is not None or archive.namelist()!=[r["path"] for r in members["members"]]: raise SystemExit("source ZIP CRC/order differs")
        for row in members["members"]:
            raw=archive.read(row["path"])
            if sha(raw)!=row["sha256"] or len(raw)!=row["bytes"]: raise SystemExit("source ZIP member differs")
    helper=retention(); originals=sorted(helper.regular_files(root))
    copies=[WORK/(PREFIX+s) for s in ("-before.json","-closed.json","-source-members.json","-sources.zip",".xml",".log","-native-start.json","-native-completion.json")]+[Path(__file__),HELPER]
    inputs=sorted({*originals,*copies}); stamps={str(p):stamp(p) for p in inputs}
    PRIVATE.mkdir(parents=True); private_zip=PRIVATE/"originals-without-credentials.zip"
    retained=helper.add_zip(private_zip,(("run/"+p.relative_to(root).as_posix(),p.read_bytes(),str(p)) for p in originals))
    with zipfile.ZipFile(private_zip) as archive:
        if archive.testzip() is not None or archive.namelist()!=[r["path"] for r in retained]: raise SystemExit("private ZIP CRC/order differs")
        for row in retained:
            raw=archive.read(row["path"])
            if sha(raw)!=row["sha256"] or len(raw)!=row["byte_count"] or sha(raw)!=stamps[row["origin"]]["sha256"]: raise SystemExit("private ZIP member differs")
    if stamps!={str(p):stamp(p) for p in inputs}: raise SystemExit("original bytes or mtimes changed during private retention")
    write_new(PRIVATE/"retention-manifest.json",{"schema":"closure-catalogue-root-private-retention-v1","archive":{"path":str(private_zip),"sha256":sha(private_zip.read_bytes()),"bytes":private_zip.stat().st_size},"members":retained,"excluded_credentials":helper.EXCLUSIONS,"pruned_reparse_paths":sorted(helper.PRUNED_LINKS),"inputs_before":stamps,"inputs_after":stamps})
    DEST.mkdir(parents=True); (DEST/".gitattributes").write_bytes(b"* -text\n")
    public={p.name:p for p in copies}; public["private-retention-manifest.json"]=PRIVATE/"retention-manifest.json"
    for name,src in public.items(): shutil.copyfile(src,DEST/name); assert (DEST/name).read_bytes()==src.read_bytes()
    (DEST/"README.md").write_text("""# Root closure/catalogue integration r1

This closed direct command completed with exit code 0 and no native session identifier. Its separate native-start and
native-completion receipts preserve that distinction. The frozen source commit is a2eaafc3ee0e4a9eb219741d8e1c10422f0f6d2b;
799 source files remained unchanged. JUnit records 33 passing synthetic checks: 10 label-isolation checks, 13 closure/catalogue
integration checks, and 10 frozen gate checks.

The label-isolation audit ran separately in the label-bearing ROOT context. The integration check used no real model, added paid API,
or formal VAL input. It is engineering evidence for the tested closure/catalogue behavior, not scientific effectiveness, full evaluator
coverage, private-data audit, or production authorization. Exact frozen source, raw reports, command receipts, and all noncredential
run-root originals are retained; private originals remain outside this public directory.
""",encoding="utf-8",newline="\n")
    manifest={"schema":"closure-catalogue-root-published-files-v1","files":[{"path":p.name,"sha256":sha(p.read_bytes()),"bytes":p.stat().st_size} for p in sorted(DEST.iterdir()) if p.name!="published-manifest.json"]}
    write_new(DEST/"published-manifest.json",manifest)
    for row in manifest["files"]:
        raw=(DEST/row["path"]).read_bytes()
        if sha(raw)!=row["sha256"] or len(raw)!=row["bytes"]: raise SystemExit("published manifest mismatch")
    if stamps!={str(p):stamp(p) for p in inputs}: raise SystemExit("original bytes or mtimes changed during public archival")
    print(json.dumps({"public_archive":str(DEST),"private_archive":str(PRIVATE),"retained_noncredential_originals":len(retained),"public_files":len(manifest["files"])+1},sort_keys=True))
if __name__=="__main__": main()
