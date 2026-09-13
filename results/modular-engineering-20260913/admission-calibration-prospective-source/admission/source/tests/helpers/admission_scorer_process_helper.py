"""Synthetic-only primary evaluator in a real child process, including failure."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from evaluation.modular.scorer_process import _load, _absolute, build_service, ScorerWorker, serve
from research_loop.modular.contracts import FrozenRecord


def main():
    parser=argparse.ArgumentParser()
    for name in ('config','config-sha256','journal'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();config=_load(_absolute(args.config,'config'),args.config_sha256)
    assert config.evaluator in ({'synthetic_mode':'normal'},{'synthetic_mode':'fail'})
    def evaluate(request):
        if config.evaluator['synthetic_mode']=='fail':raise RuntimeError('synthetic evaluator outage')
        return FrozenRecord.from_dict(({'context':1,'variable_f1':1,'relation':1} if request.data()['benchmark']=='discoverybench'
            else {'cvars':2,'transform':2,'model':2}) | {'reason':'synthetic fixture, scientific quality not measured'})
    return serve(ScorerWorker(build_service(config,evaluator=evaluate),config.panel,_absolute(args.journal,'journal')))


if __name__=='__main__':raise SystemExit(main())
