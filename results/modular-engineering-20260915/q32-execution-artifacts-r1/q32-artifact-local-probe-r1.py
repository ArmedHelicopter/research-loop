import json
import sys
from pathlib import Path

base = Path('E:/_ryanDev/AI/research-loop-modular')
root = base/'artifact-evidence-provenance'
sys.path[:0] = [str(root), str(root/'tests')]
from test_q32_prospective_execution import make_stage, fixture_response
from research_loop.modular.q32_artifacts import verify_q32_artifacts

out = base/'work/q32-artifact-local-probe-r1'
out.mkdir()
stage, packet, compiled = make_stage(out)
check = verify_q32_artifacts(stage._session.sidecar, compiled, cell=stage.cell.data(), complete=False)
seal = stage.produce(fixture_response)
check2 = verify_q32_artifacts(stage._session.sidecar, compiled, cell=stage.cell.data(), complete=False)
value = {'scope': 'non-frozen debugging probe; synthetic callbacks; no API/Docker/VAL',
         'before': check.data(), 'after': check2.data(), 'jobs': len(seal.data()['jobs'])}
(out/'outcome.json').write_text(json.dumps(value, indent=2), encoding='utf-8')
print(json.dumps(value))
