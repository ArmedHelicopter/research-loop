"""Real native port, synthetic OS peer and HTTP, configurable public response."""
import hashlib
import json
from pathlib import Path
import sys

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import ProcessTree
from research_loop.modular.grok_headless_train_solver import GrokHeadlessTrainModelPort
from research_loop.modular.train_provider import GrokHeadlessTrainProvider
from research_loop.modular.train_provider_preflight import PROGRAM_SLOTS
from tests.helpers.headless_authoring_fixture import install_synthetic_native


def headless_train_provider(root,patch,*,schemas,max_calls,response,wrapped=True):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    executable=root/'synthetic-headless.exe';executable.write_bytes(b'synthetic native identity; never launched')
    home=root/'approved-home';home.mkdir()
    _,gets=install_synthetic_native(patch,{'native_deployment':{
        'executable':str(executable),'slots':{'base':{'private_home':str(home)}}}})
    import research_loop.modular.grok_headless_transport as transport
    peer=Path(__file__).resolve().parents[1]/'fixtures/headless_train_peer.py'
    calls=[]
    def spawn(command,cwd,env,stderr):
        assert env['GROK_DISABLE_API_KEY_AUTH']=='1'
        assert not {'XAI_API_KEY','GROK_API_KEY'} & set(env)
        assert not any(Path(cwd).iterdir())
        if 'inspect' in command:args=['inspect']
        else:
            prompt_path=Path(command[command.index('--prompt-file')+1])
            prompt=prompt_path.read_text(encoding='utf-8')
            prefix='Return only JSON conforming to the supplied schema. Tools, browsing, filesystem access, and evaluation material are unavailable.\n'
            assert prompt.startswith(prefix)
            request=FrozenRecord.from_dict(json.loads(prompt[len(prefix):]))
            answer=response(request);answer=answer.data() if type(answer) is FrozenRecord else answer
            path=prompt_path.parent.parent/'synthetic-peer-answer.json'
            path.write_text(json.dumps(answer),encoding='utf-8')
            calls.append(request)
            args=[command[command.index('--session-id')+1],str(path)]
        return ProcessTree([sys.executable,str(peer),*args],cwd=cwd,env=env,stderr=stderr)
    patch.setattr(transport,'ProcessTree',spawn)
    backend=GrokHeadlessTrainModelPort(executable=executable,work_root=root/'ledger',
        private_home=home,private_profile=root/'profiles',public_cwd=root/'contexts',
        frozen_files={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in (executable,peer)},
        max_calls=max_calls,schemas=schemas,
        slot_output_caps={slot:8192 if slot in PROGRAM_SLOTS else 2048 for slot in schemas},
        slot_input_byte_caps={slot:262144 for slot in schemas},observed_main_token_cap=131072)
    return (GrokHeadlessTrainProvider(backend) if wrapped else backend),calls,gets
