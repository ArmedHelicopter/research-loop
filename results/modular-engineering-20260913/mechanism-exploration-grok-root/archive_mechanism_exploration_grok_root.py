"""Archive one completed frozen check covering two newly integrated seams."""
import hashlib,json,shutil,subprocess
from pathlib import Path
TREE=Path('E:/_ryanDev/AI/research-loop-modular/integration');WORK=TREE.parent/'work'
OUT=TREE/'results/modular-engineering-20260913/mechanism-exploration-grok-root'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,b):p.write_text(json.dumps(b,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
closed=read(WORK/'mechanism-exploration-grok-integrated-r1-closed.json')
assert closed['commit']==head and closed['source_unchanged'] and closed['exit_code']==0
assert closed['junit']['tests']>0 and all(closed['junit'][k]==0 for k in ('failures','errors','skipped'))
native=read(WORK/'grok-native-acp-root-archive-verification-r1.json')
assert native['archive_files']==48 and native['payload_zip_entries']==46 and native['all_commit_bytes_equal']
source=read(WORK/'mechanism-exploration-source-committed-root-r1.json')
assert source['head']==head and source['disk_equals_git'] and source['zip_hashes_match']
OUT.mkdir(parents=True,exist_ok=False)
for suffix in ('-before.json','-closed.json','.xml'):
 p=WORK/('mechanism-exploration-grok-integrated-r1'+suffix);shutil.copyfile(p,OUT/p.name)
for name in ('mechanism-exploration-root-source-review-r1.md','mechanism-exploration-source-committed-root-r1.json',
 'grok-native-acp-root-archive-verification-r1.json','resolve_mechanism_exploration_scorer_integration.py'):
 shutil.copyfile(WORK/name,OUT/name)
shutil.copyfile(__file__,OUT/Path(__file__).name)
write(OUT/'FINAL-VERIFICATION.json',{'source_commit':head,'source_files':closed['source_count'],
 'source_unchanged':True,'junit':closed['junit'],'junit_sha256':closed['report_sha256'],
 'coverage':'28 of 36 pair controllers; 2 of 5 triple controllers; synthetic engineering only',
 'mechanism_exploration_grid':{'cells':24,'scripted_model_calls':72,'source_qualifications':48,
 'actual_docker':72,'actual_scorer_process_calls':24,'retrieval_calls':24},
 'source_archive':{'files':15,'indexed':14,'zip_members':1937,'isolated_checks':101},
 'native_archive':{'files':48,'payload_zip_entries':46,'accepted_constant_attempt':3,
 'main_reported_total_tokens':2301,'main_reported_cost_usd':0.00116892,
 'title_usage_unknown':True,'all_opportunity_totals_unknown':True,'final_settlement_unknown':True},
 'root_scope':'native ACP protocol fixtures; complete mechanism grid and original replay attacks; merged family scopes including complete history-built panel; label isolation',
 'new_generation_calls':0,'validation_opened':False,'scientific_effectiveness_proven':False})
write(OUT/'SHA256.json',{p.name:sha(p) for p in OUT.iterdir() if p.is_file()})
print(json.dumps({'root_files':len(list(OUT.iterdir())),'junit':closed['junit']}))
