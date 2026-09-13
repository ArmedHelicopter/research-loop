from pathlib import Path
import json,hashlib,shutil,zipfile,subprocess
repo=Path('E:/_ryanDev/AI/research-loop-modular/grok-provider-repair');work=repo.parent/'work'
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip();check=work/('grok-provider-repair-frozen-'+head[:7])
closure=json.loads((check/'closure.json').read_text());assert closure['exit_code']==0 and closure['source_unchanged']
archive=repo/'results/grok-public-train-provider-repair-20260914';archive.mkdir(exist_ok=False)
(archive/'.gitattributes').write_bytes(b'** -text\n')
index={}
def copy(source,target):
 source=Path(source);target=archive/target;target.parent.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(source,target);assert source.read_bytes()==target.read_bytes();index[str(source.resolve())]=target.relative_to(archive).as_posix()
def tree(source,target):
 for p in Path(source).rglob('*'):
  if p.is_file() and not p.is_symlink() and p.name!='auth.json':copy(p,Path(target)/p.relative_to(source))
for name in ('closure.json','source-before.json','command.json','junit.xml','stdout.txt'):copy(check/name,'final-check/'+name)
for tag,root in [('failed-9ad2fd9',repo/'work/check-9ad2fd9'),('passed-a23fb2a',work/'grok-provider-repair-check-a23fb2a')]:
 for name in ('junit.xml','stdout.txt'):copy(root/name,'prior-repair-checks/'+tag+'/'+name)
for p in sorted(work.glob('grok-solver-provider-*.xml')):copy(p,'prior-provider-checks/'+p.name)
for p in sorted(work.glob('grok-solver-provider-*-closed.json')):copy(p,'prior-provider-checks/'+p.name)
for p in sorted(work.glob('grok-solver-provider-*-before.json')):copy(p,'prior-provider-checks/'+p.name)
copy(repo/'results/grok-public-train-provider-20260914.zip','original-14-test-checkpoint.zip')
summary=[]
for number,case in enumerate(('complete-panel','unknown-main','provenance-fault')):
 root=check/'pytest'/('test_v4_full_useful_eight_cell'+str(number))
 for folder in ('native-ledger','run-v4','export','export-audit'):tree(root/folder,Path(case)/folder)
 for name in ('client-0.jsonl','worker-0.jsonl','synthetic-grok.exe'):
  if (root/name).exists():copy(root/name,case+'/'+name)
 ledger=json.loads((root/'native-ledger/ledger.json').read_text());attempt=json.loads((root/'run-v4/controller-attempt.json').read_text())
 summary.append({'case':case,'main_opportunities':len(ledger['calls']),'possible_title_opportunities':len(ledger['calls']),'known_main_tokens':ledger['tokens'],'usage_incomplete':ledger['usage_incomplete'],'planned_cells':len(attempt['cells']),'scorer_calls':attempt['actual_scorer_calls'],'docker_receipts':sum('execution_receipt' in row for row in attempt['cells']),'statuses':[row['status'] for row in attempt['cells']]})
# Include only synthetic public/runtime artifacts from substitution cases; no login files.
for root in sorted((check/'pytest').glob('test_native_original_substitut[0-9]*')):
 tree(root/'native-ledger',Path('negative-originals')/root.name/'native-ledger')
for name in ('research_loop/modular/grok_train_solver.py','research_loop/modular/grok_acp_transport.py','research_loop/modular/combination_train_controller.py','tests/fixtures/grok_acp_peer.py','tests/test_grok_train_solver.py','docs/GROK-PUBLIC-TRAIN-PROVIDER.md'):copy(repo/name,'source/'+name)
copy(work/'verify-grok-provider-repair.py','verification/run_frozen_check.py')
copy(Path(__file__),'verification/build_archive.py')
(archive/'ORIGINAL_PATHS.json').write_text(json.dumps(index,indent=2))
report={'source_commit':head,'base_commit':'c02e4b8d2d0b10e6741167b84ee2b6c0199df218','cases':summary,'real_model_or_api_calls':0,'native_version_contract':'v1.0.13','dispatch_scope':'M4/M5 useful-control v4 only','historical_failure_stdout':'not found; original failing XML with detailed traceback and matching recorded hash is included','auth_files_included':False,'actual_private_references_included':False}
(archive/'SUMMARY.json').write_text(json.dumps(report,indent=2))
(archive/'README.txt').write_text('Synthetic public Grok TRAIN provider repair evidence. Source '+head+'\n\nThe complete-panel contains 40 native original request/response/reservation records,\neight actual Docker receipts and runtime traces, and eight independent scorer\nreceipts plus both process journals. Unknown MAIN and provenance-fault cases\nretain their complete planned denominators and known usage. No real model/API\ncalls were made. Title usage/all-opportunity settlement remain unknown.\n\nOriginal files were copied byte-for-byte. ORIGINAL_PATHS.json maps unchanged\nabsolute references to included copies; auth files and private reference stores\nare deliberately excluded. Original caller paths are provenance, not portable\nlaunch instructions. The original 14-test archive and recovered failing XML\nare retained. Historical stdout was not present; no replacement is fabricated.\n\nAdmission covers only M4/M5 useful-control v4. Other controller admissions\nare unchanged. Engineering success is not scientific validation.\n')
manifest=[{'path':p.relative_to(archive).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(archive.rglob('*')) if p.is_file()]
(archive/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2))
zip_path=archive.with_suffix('.zip')
with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(archive.rglob('*')):
  if p.is_file():z.write(p,p.relative_to(archive).as_posix())
with zipfile.ZipFile(zip_path) as z:
 assert z.testzip() is None
 assert set(z.namelist())=={p.relative_to(archive).as_posix() for p in archive.rglob('*') if p.is_file()}
 assert all(z.read(p.relative_to(archive).as_posix())==p.read_bytes() for p in archive.rglob('*') if p.is_file())
print(json.dumps({'files':len(manifest)+1,'source':head,'zip_sha256':hashlib.sha256(zip_path.read_bytes()).hexdigest(),'cases':summary},indent=2))
