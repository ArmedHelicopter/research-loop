"""Read retained native logs; publish only explicit fixed messages and safe fields."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

WORK = Path(__file__).parent
OUTPUT = WORK / 'grok-headless-initialize-location-r2'
INPUT = WORK / 'existing-headless-log-stage-comparison-r1.json'
FIELDS = {
    'startup phase': {'phase': str, 'elapsed_ms': int},
    'startup phase running long': {'phase': str, 'open_ms': int},
    'startup timing': {'name': str, 'elapsed_ms': int},
    'model catalog: auth refresh watcher started': {'had_real_catalog': bool, 'model_count': int},
    'auth init user_info check': {'needs_user_info': bool},
    'auth init disk refresh': {'changed': bool},
    'auth init token state': {'has_current': bool, 'is_expired': bool},
    'auth method selection': {'default_auth_method_id': str, 'has_external_api_key': bool,
                              'has_cached_token': bool, 'methods_count': int},
    'pager started': {'mode': str},
    'agent initialized': {},
    'auth started': {},
    'session created': {},
    'prompt received': {},
    'shell.turn.inference_start': {},
    'shell.turn.inference_done': {},
}
ENUMS = {'phase': {'managed_policy','bootstrap','model_catalog','worker_spawn',
                   'acp_initialize','eager_auth','session_create'},
         'default_auth_method_id': {'cached_token'}, 'mode': {'headless'}}
TIMING_NAMES = {'startup.early_prefetch_launch','startup.http_blocking_client_build',
    'startup.fetch_models_blocking','startup.early_models_fetch','startup.early_settings_fetch',
    'startup.early_prefetch','startup.bootstrap.remote_settings','startup.bootstrap.resolve_config',
    'startup.http_client_build','startup.bootstrap.init_process','startup.bootstrap.models_manager'}
ENUMS['name'] = TIMING_NAMES

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def main():
    OUTPUT.mkdir(exist_ok=False)
    inputs = json.loads(INPUT.read_bytes())['variants']
    result = {'schema':'retained-headless-startup-location-v2', 'new_native_calls':0,
              'new_model_calls':0, 'original_outcomes_changed':False,
              'extractor_sha256':digest(Path(__file__).read_bytes()), 'variants':{}}
    for name, metadata in inputs.items():
        path = Path(metadata['source'])
        before = path.stat()
        raw = path.read_bytes()
        assert digest(raw) == metadata['source_sha256']
        events = []
        for line in raw.splitlines():
            row = json.loads(line)
            message = row.get('msg')
            if message not in FIELDS:
                continue
            context = row.get('ctx') or {}
            timestamp = row.get('ts')
            assert isinstance(timestamp, str)
            instant = datetime.fromisoformat(timestamp.replace('Z','+00:00'))
            assert instant.utcoffset() is not None
            fields = {}
            for key, kind in FIELDS[message].items():
                value = context.get(key)
                if type(value) is not kind:
                    continue
                if kind is str and value not in ENUMS[key]:
                    continue
                fields[key] = value
            if message == 'startup timing' and 'name' not in fields:
                continue
            events.append({'timestamp':timestamp, 'message':message, 'fields':fields})
        assert path.stat().st_mtime_ns == before.st_mtime_ns and path.read_bytes() == raw
        result['variants'][name] = {'source':str(path), 'source_sha256':digest(raw),
            'source_bytes':len(raw), 'source_mtime_ns':before.st_mtime_ns,
            'source_unchanged':True, 'events':events}
    (OUTPUT/'observation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(OUTPUT/'observation.json'),
        'event_counts':{k:len(v['events']) for k,v in result['variants'].items()},
        'native_calls':0,'model_calls':0}))

if __name__ == '__main__':
    main()
