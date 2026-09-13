from pathlib import Path
import hashlib,json,subprocess,os,time,sys,xml.etree.ElementTree as ET
repo=Path('E:/_ryanDev/AI/research-loop-modular/grok-provider-repair')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
root=Path('E:/_ryanDev/AI/research-loop-modular/work')/('grok-provider-repair-frozen-'+head[:7]);root.mkdir(exist_ok=False);(root/'temp').mkdir()
def snapshot():
 paths=subprocess.check_output(['git','ls-files'],cwd=repo,text=True).splitlines()
 return {name:hashlib.sha256((repo/name).read_bytes()).hexdigest() for name in paths if not name.startswith(('results/','data/'))}
before=snapshot();(root/'source-before.json').write_text(json.dumps({'commit':head,'files':before},indent=2))
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)
command=[sys.executable,'-m','pytest','tests/test_grok_train_solver.py','tests/test_grok_acp_transport.py','tests/test_label_isolation.py','tests/test_m4_m5_useful_controls.py::test_eight_cell_useful_output_grid','tests/test_modular_combination_train_controller.py::test_real_custody_complete_eight_cells_port_docker_signed_scorer_and_contrast','-q','--basetemp',str(root/'pytest'),'--junitxml',str(root/'junit.xml')]
(root/'command.json').write_text(json.dumps(command,indent=2));env=dict(os.environ,TEMP=str(root/'temp'),TMP=str(root/'temp'));started=time.monotonic()
with (root/'stdout.txt').open('wb') as out:code=subprocess.call(command,cwd=repo,env=env,stdout=out,stderr=subprocess.STDOUT)
after=snapshot();summary={'commit':head,'exit_code':code,'source_unchanged':before==after,'source_count':len(after),'source_after':after,'wall_seconds':time.monotonic()-started,'actual_provider_calls':0,'provider':'synthetic ACP peers only','junit_sha256':hashlib.sha256((root/'junit.xml').read_bytes()).hexdigest()}
suite=ET.parse(root/'junit.xml').find('testsuite');summary['junit']={k:int(suite.attrib[k]) for k in ('tests','failures','errors','skipped')};(root/'closure.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items() if k!='source_after'},indent=2),flush=True);print(root,flush=True);sys.exit(code)
