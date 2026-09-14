"""Exercise the two owned-process cleanup paths without launching Grok."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

path=Path(__file__).with_name('driver.py')
spec=importlib.util.spec_from_file_location('observed_driver',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
closed=[]
def start(self,*args,**kwargs):self.process=object()
def stop(self):closed.append(self)
with patch.object(module.OriginalTree,'__init__',start),patch.object(module.OriginalTree,'close',stop):
    with patch.object(module.threading.Thread,'start',side_effect=RuntimeError('synthetic startup fault')):
        try:module.ObservedTree([])
        except OSError:pass
        else:raise AssertionError('engine-caught startup failure required')
    assert len(closed)==1
    instance=object.__new__(module.ObservedTree)
    class WaitingObserver:
        def set(self):pass
        def join(self,timeout):assert timeout==5
        def is_alive(self):return True
    instance.observer_stop=instance.observer=WaitingObserver()
    try:instance.close()
    except OSError:pass
    else:raise AssertionError('engine-caught shutdown failure required')
    assert len(closed)==2 and module.OBSERVER_STATUS['fault']=='observer_did_not_close'
print(json.dumps({'cleanup_checks':2,'passed':2,'native_launches':0,'model_calls':0}))
