import hashlib,json,subprocess,sys
from pathlib import Path
root=Path('E:/_ryanDev/AI/research-loop-modular/q32-execute')
files=subprocess.check_output(['git','ls-files','research_loop','evaluation','tests','docs','pyproject.toml','AGENTS.md'],cwd=root,text=True).splitlines()
manifest={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files if (root/p).is_file()}
Path(sys.argv[1]).write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'count':len(manifest),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'manifest_sha256':hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()}))
