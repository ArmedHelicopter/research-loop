"""Prepare-only archive for the closed r2 initialize-only/CDB diagnostic."""
from __future__ import annotations
import hashlib, importlib.util, json, shutil, zipfile
from pathlib import Path

BASE=Path(r"E:\_ryanDev\AI\research-loop-modular"); WORK=BASE/"work"
SOURCE=WORK/"grok130-initialize-stack-r2"
DEST=BASE/"artifact-evidence-provenance"/"results"/"modular-engineering-20260915"/"grok-initialize-stack-r2"
PRIVATE=BASE/"retained-private-evidence"/"grok-initialize-stack-r2"
HELPER=WORK/"prepare_headless_lineage_full4_archive_r1.py"; PREFIX="grok130-initialize-stack-r2"; SESSION=44315

def sha(raw): return hashlib.sha256(raw).hexdigest()
def stamp(p):
    raw=p.read_bytes(); return {"sha256":sha(raw),"bytes":len(raw),"mtime_ns":p.stat().st_mtime_ns}
def read(p): return json.loads(p.read_bytes())
def write_new(p,value):
    with p.open("xb") as out: out.write((json.dumps(value,ensure_ascii=False,indent=2)+"\n").encode())
def retention():
    spec=importlib.util.spec_from_file_location("initialize_stack_r2_retention",HELPER)
    if spec is None or spec.loader is None: raise RuntimeError("retention helper is not loadable")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def main():
    if DEST.exists() or PRIVATE.exists(): raise SystemExit("refusing to overwrite archive destinations")
    if not SOURCE.is_dir(): raise SystemExit("closed r2 diagnostic root is missing")
    start=read(WORK/(PREFIX+"-native-start.json")); join=read(WORK/(PREFIX+"-native-join.json")); closure=read(SOURCE/"closure.json"); result=closure.get("result",{})
    if (start.get("session_id")!=SESSION or join.get("native_session_id")!=SESSION or join.get("result",{}).get("exit_code")!=0
            or result.get("elapsed_seconds")!=17.594000000011874 or result.get("response",{}).get("response_elapsed_seconds")!=17.453999999997905
            or result.get("accepted_initialize") is not False or result.get("faults")!=["extra_captured_frame","unexpected_notification"]
            or result.get("server_requests_observed")!=0 or result.get("initialize_writes_completed")!=1
            or result.get("outbound_method_counts",{}).get("session/new")!=0 or result.get("outbound_method_counts",{}).get("session/prompt")!=0
            or result.get("outbound_method_counts",{}).get("authenticate")!=0 or result.get("outbound_method_counts",{}).get("_x.ai/billing")!=0
            or result.get("outbound_method_counts",{}).get("_x.ai/auto-topup-rule")!=0 or closure.get("model_prompt_writes")!=0
            or not result.get("process_tree_closed") or not closure.get("source_unchanged") or not closure.get("global_auth_metadata_unchanged")
            or result.get("known_model_usage") is not None or result.get("settled_additional_charge_usd") is not None): raise SystemExit("closed r2 outcome differs")
    cdb=closure.get("cdb_stack_capture",{})
    if (cdb.get("pid")!=13616 or cdb.get("frame_count")!=400 or cdb.get("frame_count_source")!="private_stdout"
            or cdb.get("elapsed_seconds")!=1.5309999999881256 or cdb.get("exit_code")!=0 or cdb.get("status")!="capture_success_established"
            or not cdb.get("child_alive_after_detach") or cdb.get("detach_independently_observed") is not False): raise SystemExit("CDB r2 receipt differs")
    helper=retention(); originals=sorted(helper.regular_files(SOURCE))
    public_names=("driver.py","init_engine.py","stack_capture.py","parser_smoke.py","README.md","fixture-diagnosis-r2.md","cdb-argument-diagnosis-r1.md",
        "launch-reservation.json","envelope.json","closure.json","help-receipt.json","agent-help.stdout.txt","agent-help.stderr.txt","cdb-help-result.json","cdb-help.txt","cdb-help.stderr.txt","preparation-manifest.json")
    copies=[SOURCE/name for name in public_names]+[WORK/(PREFIX+"-native-start.json"),WORK/(PREFIX+"-native-join.json"),Path(__file__),HELPER]
    if any(not p.is_file() for p in copies): raise SystemExit("declared public r2 evidence is missing")
    inputs=sorted({*originals,*copies}); before={str(p):stamp(p) for p in inputs}
    PRIVATE.mkdir(parents=True); private_zip=PRIVATE/"originals-without-credentials.zip"
    private_members=helper.add_zip(private_zip,(("stack-r2/"+p.relative_to(SOURCE).as_posix(),p.read_bytes(),str(p)) for p in originals))
    with zipfile.ZipFile(private_zip) as z:
        if z.testzip() is not None or z.namelist()!=[r["path"] for r in private_members]: raise SystemExit("private ZIP CRC/order differs")
        for row in private_members:
            raw=z.read(row["path"])
            if sha(raw)!=row["sha256"] or len(raw)!=row["byte_count"] or sha(raw)!=before[row["origin"]]["sha256"]: raise SystemExit("private ZIP member differs")
    if before!={str(p):stamp(p) for p in inputs}: raise SystemExit("original bytes or mtimes changed during private retention")
    write_new(PRIVATE/"retention-manifest.json",{"schema":"grok-initialize-stack-r2-private-retention-v1","archive":{"path":str(private_zip),"sha256":sha(private_zip.read_bytes()),"bytes":private_zip.stat().st_size},"members":private_members,"excluded_credentials":helper.EXCLUSIONS,"pruned_reparse_paths":sorted(helper.PRUNED_LINKS),"inputs_before":before,"inputs_after":before})
    DEST.mkdir(parents=True); (DEST/".gitattributes").write_bytes(b"* -text\n")
    public={"public/"+p.name:p for p in copies}
    for name,src in public.items():
        target=DEST/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(src,target)
        if target.read_bytes()!=src.read_bytes(): raise SystemExit("public copy differs")
    envelope=read(SOURCE/"envelope.json"); rows=[]
    with zipfile.ZipFile(DEST/"frozen-python-sources.zip","x",zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for origin,expected in sorted(envelope.get("frozen_files",{}).items()):
            p=Path(origin)
            if p.suffix!=".py": continue
            raw=p.read_bytes()
            if sha(raw)!=expected: raise SystemExit("frozen Python source differs")
            member="source/"+p.name
            if any(row["member"]==member for row in rows): raise SystemExit("ambiguous source basename")
            z.writestr(member,raw); rows.append({"member":member,"origin":str(p),"sha256":expected,"bytes":len(raw)})
    with zipfile.ZipFile(DEST/"frozen-python-sources.zip") as z:
        if z.testzip() is not None or z.namelist()!=[r["member"] for r in rows]: raise SystemExit("source ZIP CRC/order differs")
        for row in rows:
            raw=z.read(row["member"])
            if sha(raw)!=row["sha256"] or len(raw)!=row["bytes"]: raise SystemExit("source ZIP member differs")
    write_new(DEST/"frozen-source-members.json",{"schema":"grok-initialize-stack-r2-frozen-source-v1","members":rows,"zip_sha256":sha((DEST/"frozen-python-sources.zip").read_bytes())})
    (DEST/"README.md").write_text("""# Grok initialize stack diagnostic r2

Native session 44315 joined with exit code 0. One initialize request produced a response at 17.454 seconds and the driver closed at
17.594 seconds, but `accepted_initialize` is false: the retained closure records `extra_captured_frame` and `unexpected_notification`.
This is an observed protocol diagnostic, not a usable production initialization or model result. It made zero server requests and wrote
one initialize plus zero session/new, session/prompt, authenticate, billing, and auto-topup RPCs. No prompt was sent. Usage and
settlement remain unknown; no zero-usage claim is made.

CDB captured 400 frames from private stdout in 1.531 seconds with exit code 0. The child was alive after detach, while detach was not
independently observed. Brief suspension timing is noncomparable. The capture confirms only the recorded diagnostic capture result;
it does not establish a production-safe model call, root cause, source/binary equivalence, authentication health, or a repair.

Public files contain helpers, frozen Python sources, help/preparation/closure/start/join receipts and source-only fixture/CDB notes.
Raw stacks, native logs, stdout/stderr, profile/home material and auth files are not public; noncredential originals are privately retained.
No actual private/VAL benchmark input, model prompt, added paid API, C5, or M4/M5 experiment is represented here.
""",encoding="utf-8",newline="\n")
    manifest={"schema":"grok-initialize-stack-r2-published-files-v1","files":[{"path":p.relative_to(DEST).as_posix(),"sha256":sha(p.read_bytes()),"bytes":p.stat().st_size} for p in sorted(DEST.rglob("*")) if p.is_file() and p.name!="published-manifest.json"]}
    write_new(DEST/"published-manifest.json",manifest)
    for row in manifest["files"]:
        raw=(DEST/row["path"]).read_bytes()
        if sha(raw)!=row["sha256"] or len(raw)!=row["bytes"]: raise SystemExit("published manifest mismatch")
    if before!={str(p):stamp(p) for p in inputs}: raise SystemExit("original bytes or mtimes changed during public archival")
    print(json.dumps({"public_archive":str(DEST),"private_archive":str(PRIVATE),"private_noncredential_members":len(private_members),"public_files":len(manifest["files"])+1},sort_keys=True))
if __name__=="__main__": main()
