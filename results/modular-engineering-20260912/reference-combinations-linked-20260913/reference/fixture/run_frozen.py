import hashlib, json, os, subprocess, sys, time
from pathlib import Path
TREE=Path('E:/_ryanDev/AI/research-loop-modular/pr-ref')
WORK=Path('E:/_ryanDev/AI/research-loop-modular/work/primary-reference-checks')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()
assert head=='574bfbf'+subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip()[7:]
assert not subprocess.check_output(['git','status','--porcelain'],cwd=TREE)
files=subprocess.check_output(['git','ls-files','evaluation','research_loop','tests'],cwd=TREE,text=True).splitlines()
sources={p:sha(TREE/p) for p in files if p.endswith('.py')}
freeze={'schema':'primary-reference-source-freeze-v1','source_commit':head,'files':sources,'python':sys.executable,
        'base_commit':'b9f7ff46030f16ddfe321c616bf863b92fc9a08c','frozen_at_epoch':time.time()}
with (WORK/'source-freeze-r1.json').open('x') as f:json.dump(freeze,f,indent=2)
tests=['tests/test_primary_reference_bridge.py','tests/test_train_reference_store.py','tests/test_primary_prospective_exporter.py',
    'tests/test_primary_process_qualification.py','tests/test_modular_train_io.py','tests/test_label_isolation.py',
    'tests/test_scorer_process.py','tests/test_combination_scorer_process.py','tests/test_modular_train_controller.py']
command=[sys.executable,'-m','pytest',*tests,'-q','--basetemp',str(WORK/'frozen-r1'),'--junitxml',str(WORK/'frozen-r1.xml')]
with (WORK/'frozen-command-r1.json').open('x') as f:json.dump({'command':command,'cwd':str(TREE)},f,indent=2)
with (WORK/'frozen-r1.log').open('xb') as log:
    process=subprocess.run(command,cwd=TREE,stdout=log,stderr=subprocess.STDOUT)
after={p:sha(TREE/p) for p in sources}
result={'schema':'primary-reference-frozen-test-result-v1','exit_code':process.returncode,'source_commit_before':head,
    'source_commit_after':subprocess.check_output(['git','rev-parse','HEAD'],cwd=TREE,text=True).strip(),
    'all_source_bytes_unchanged':sources==after,'worktree_clean':not bool(subprocess.check_output(['git','status','--porcelain'],cwd=TREE)),
    'source_file_count':len(sources),'source_files_after':after,'junit_sha256':sha(WORK/'frozen-r1.xml'),
    'log_sha256':sha(WORK/'frozen-r1.log'),'source_freeze_sha256':sha(WORK/'source-freeze-r1.json')}
with (WORK/'frozen-result-r1.json').open('x') as f:json.dump(result,f,indent=2)
print(json.dumps({key:value for key,value in result.items() if key!='source_files_after'}))
