"""Windows-only, closed filesystem/config policy for isolated 1.0.30 readiness.

The official path-prefix filter excludes ordinary skills, including later bundle
downloads. Plugin discovery is separate: every source must remain absent.
No credential or skill body is read by the filesystem observer.
"""
import json
import os
from pathlib import Path
import stat

from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError

BUILTIN_COMMANDS = frozenset(('compact', 'always-approve', 'context', 'session-info', 'feedback'))
DISCOVERY_DIRS = ('.grok', '.agents', '.claude', '.cursor')


def _require(value, message):
    if not value:
        raise ContractError('skill_isolation_' + message)


def context_record(cwd, home, user):
    _require(os.name == 'nt', 'windows_only')
    roots = tuple(Path(p).absolute() for p in (cwd, home, user))
    for root in roots:
        _require(root == root.resolve(), 'path_alias')
    _require(all(a != b and a not in b.parents and b not in a.parents
                 for i, a in enumerate(roots) for b in roots[i + 1:]), 'roots_overlap')
    cwd, home, user = roots
    # All ancestor contexts are rejected, rather than silently inheriting a
    # repository, config layer, marketplace registry or workspace-user source.
    absent = {p / name for p in (cwd, *cwd.parents) for name in (*DISCOVERY_DIRS, '.git')}
    absent.update(user / name for name in DISCOVERY_DIRS)
    absent.update(home / name for name in ('plugins', 'managed_config.toml',
                                         'requirements.toml'))
    return FrozenRecord.from_dict({'schema': 'grok130-readiness-context-v1',
        'cwd': str(cwd), 'private_home': str(home), 'private_profile': str(user),
        'ordinary_skill_ignore_prefixes': sorted({str(p) for p in roots} |
            {str(p / name) for p in cwd.parents for name in DISCOVERY_DIRS}),
        'absent_discovery_sources': sorted(str(p) for p in absent),
        'plugin_source_policy': 'no-discovered-or-configured-plugin-sources',
        'source_semantics': 'public-bc7f02eddd3d84085849dc19ed216f11c23b0571',
        'binary_source_equivalence_verified': False})


def isolated_config(cwd, home, user):
    from research_loop.modular.grok_acp_transport import SAFE_CONFIG
    body = context_record(cwd, home, user).data()
    prefixes = json.dumps(body['ordinary_skill_ignore_prefixes'], ensure_ascii=True)
    return SAFE_CONFIG.replace('[skills]\ndisabled = []',
        '[skills]\npaths = []\nserver_skill_dirs = []\nbundled_skill_dirs = []\n'
        'ignore = ' + prefixes + '\ndisabled = []').replace(
        '[plugins]\nenabled = []', '[plugins]\npaths = []\nenabled = []')


def observe_context(record):
    _require(type(record) is FrozenRecord, 'record_type')
    body = record.data()
    _require(record == context_record(body['cwd'], body['private_home'], body['private_profile']),
             'record_binding')
    roots = [Path(body[k]) for k in ('cwd', 'private_home', 'private_profile')]
    for root in roots:
        for parent in (root, *root.parents):
            _require(not (parent.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                     'path_reparse_point')
    for name in body['absent_discovery_sources']:
        # lexists rejects broken links too; never follows a discovery link.
        _require(not os.path.lexists(name), 'unexpected_discovery_source')
    _require(not any(roots[0].iterdir()), 'cwd_changed')
    count = 0
    for root in roots:
        for directory, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                count += 1
                _require(count <= 10000, 'inventory_bound')
                path = Path(directory) / name
                _require(not (path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                         'content_reparse_point')
    # The native CLI creates this empty registry lock even with no installed
    # plugins. A lock is not a plugin source. Registry data or other entries
    # remain unadmitted; content links have already been rejected above.
    installed = roots[1] / 'installed-plugins'
    if installed.exists():
        _require(installed.is_dir(), 'installed_registry_shape')
        for entry in installed.iterdir():
            _require(entry.name == 'registry.lock' and entry.is_file()
                     and entry.stat().st_size == 0, 'unexpected_discovery_source')
    config = roots[1] / 'config.toml'
    _require(config.read_text(encoding='utf-8') == isolated_config(*roots), 'config_changed')
    return {'schema': 'grok130-readiness-context-observation-v1',
        'context_digest': record.content_hash, 'discovery_sources_absent': True,
        'ignored_bundle_present': (roots[1] / 'bundled').exists(),
        'ordinary_skill_filter_applies_to_later_bundles': True,
        'direct_model_context_inspection': False}
