"""Synthetic ACP stream using the old peer's MAIN/accounting implementation.

Only this child reads the synthetic skill fixture. Its small projection models
the pinned public path-prefix filter; it is not a native-binary behavior proof.
"""
import json
import os
from pathlib import Path
import runpy
import sys
import tomllib

mode, log = sys.argv[1:]
original_stdout = sys.stdout
names = ['compact', 'always-approve', 'context', 'session-info', 'feedback']
fired = False


def raw(value):
    original_stdout.write(json.dumps(value) + '\n')
    original_stdout.flush()


def reload_frame():
    frame = {'jsonrpc': '2.0', 'id': 'skills-reload', 'result': {'result': {'reloaded': 1}}}
    if mode == 'unknown_id': frame['id'] = 'future-reload'
    if mode == 'flat_result': frame['result'] = {'reloaded': 1}
    if mode == 'bool_count': frame['result']['result']['reloaded'] = True
    if mode == 'two_sessions': frame['result']['result']['reloaded'] = 2
    if mode == 'extra_field': frame['extra'] = 0
    if mode == 'error': frame = {'jsonrpc': '2.0', 'id': 'skills-reload', 'error': {'code': -1}}
    raw(frame)


class Stream:
    def write(self, text):
        global fired
        if text == '\n': return 1
        row = json.loads(text)
        update = row.get('params', {}).get('update', {})
        kind = update.get('sessionUpdate')
        if kind == 'available_commands_update':
            update['availableCommands'] = [{'name': name, 'description': 'synthetic built-in'} for name in names]
            if mode == 'foreign_session': row['params']['sessionId'] = '00000000-0000-4000-8000-000000000002'
            if mode == 'extra_command': update['availableCommands'].append({'name': 'unapproved-skill'})
            if mode == 'tools': update['_meta']['tools'] = ['read_file']
        if mode == 'early_reload' and row.get('id') == 2:
            reload_frame()
        if kind == 'agent_message_chunk' and not fired:
            fired = True
            home = Path(os.environ['GROK_HOME'])
            skill = home / 'bundled' / 'skills' / 'synthetic' / 'SKILL.md'
            skill.parent.mkdir(parents=True)
            skill.write_text('---\nname: synthetic\ndescription: MUST NOT ENTER CONTEXT\n---\nsecret fixture instruction')
            config = tomllib.loads((home / 'config.toml').read_text())
            ignores = [Path(p).resolve() for p in config['skills'].get('ignore', [])]
            included = not any(skill.resolve().is_relative_to(p) for p in ignores)
            Path(log + '.context.json').write_text(json.dumps({'ordinary_skill_included': included,
                'system_reminder_injected': included, 'builtin_commands': names,
                'synthetic_projection_only': True}))
            if included:
                raw({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId':
                    row['params']['sessionId'], 'update': {'sessionUpdate': 'available_commands_update',
                    'availableCommands': [{'name': 'synthetic'}], '_meta': {'tools': []}}}})
            if mode == 'plugin_arrival':
                plugin = home / 'plugins' / 'synthetic'; plugin.mkdir(parents=True)
                (plugin / 'SKILL.md').write_text('synthetic plugin')
            if mode == 'managed_arrival': (home / 'managed_config.toml').write_text('[skills]\npaths=["E:/outside"]')
            if mode == 'config_drift':
                with (home / 'config.toml').open('a') as out: out.write('\n')
            if mode not in ('no_rpc', 'plugin_arrival', 'managed_arrival', 'config_drift'):
                reload_frame()
        if mode == 'no_main_result' and row.get('id') == 5:
            return len(text)
        raw(row)
        return len(text)

    def flush(self): original_stdout.flush()


sys.stdout = Stream()
sys.argv = [str(Path(__file__).with_name('grok_acp_peer.py')), 'ok', log]
runpy.run_path(sys.argv[0], run_name='__main__')
