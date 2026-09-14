"""Default native entry with only its final OS-spawn seam replaced by a peer."""
import json
from pathlib import Path
import sys

from research_loop.modular import grok_acp_transport as transport
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_train_solver import GrokTrainModelPort
from research_loop.modular.train_provider import GrokTrainProvider


def native_phase_provider(root,patch,*,schemas,max_calls,response,fault_at=None):
    root.mkdir(parents=True,exist_ok=True)
    exe=root/'synthetic-grok.exe';exe.write_bytes(b'phase fixture executable identity; never launched')
    home=root/'approved-login';home.mkdir();(home/'auth.json').write_text('{}')
    peer=(Path(__file__).parents[1]/'fixtures/grok_phase_peer.py').resolve();logs=[]
    original=transport.ProcessTree
    def spawn(command,cwd,env,stderr):
        assert list(command)==[str(exe.resolve()),'--no-auto-update','--cwd',str(cwd),'agent','stdio']
        assert not any(Path(cwd).iterdir())
        assert all(p.is_dir() for p in Path(env['USERPROFILE']).rglob('*'))
        assert not {'XAI_API_KEY','GROK_API_KEY'} & set(env)
        call=Path(env['GROK_HOME']).parent
        assert (Path(env['GROK_HOME'])/'config.toml').read_text()==transport.diagnostic_config(2048)
        request=FrozenRecord.from_dict(json.loads((call/'request.private.json').read_bytes()))
        answer=response(request);answer=answer.data() if type(answer) is FrozenRecord else answer
        log=call/'peer.jsonl';log.with_suffix('.answer.json').write_text(json.dumps(answer),encoding='utf-8')
        logs.append(log);fault='unknown_main' if len(logs)==fault_at else 'ok'
        return original([sys.executable,str(peer),str(log),fault],cwd,env,stderr)
    patch.setattr(transport,'EXECUTABLE_SHA256',transport.digest(exe.read_bytes()))
    patch.setattr(transport,'ProcessTree',spawn)
    backend=GrokTrainModelPort(executable=exe,work_root=root/'native-ledger',private_home=home,
        private_profile=root/'profiles',public_cwd=root/'public-contexts',
        frozen_files={str(peer):transport.digest(peer.read_bytes())},max_calls=max_calls,schemas=schemas,
        slot_output_caps={s:2048 for s in schemas},slot_input_byte_caps={s:1048576 for s in schemas},
        observed_main_token_cap=max_calls*131072)
    return GrokTrainProvider(backend),logs
