import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import pytest
from driver import run_once, WIRE

@pytest.mark.parametrize('mode,fault', [('success', None), ('malformed', 'malformed_json'),
    ('server_request', 'unsolicited_server_request'), ('timeout', 'timeout')])
def test_exactly_one_initialize_and_owned_cleanup(tmp_path, mode, fault):
    source = Path(__file__).parent
    pinned = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('*.py')}
    result = run_once([sys.executable, str(source / 'fixture_peer.py'), mode, str(tmp_path)],
        cwd=tmp_path, env=dict(os.environ), directory=tmp_path / 'receipt', frozen_files=pinned,
        timeout=2 if mode == 'timeout' else 10)
    assert (tmp_path / 'received.private.jsonl').read_bytes() == WIRE
    assert result['outbound_method_counts'] == {'initialize': 1, 'session/new': 0, 'authenticate': 0,
        '_x.ai/billing': 0, '_x.ai/auto-topup-rule': 0, 'session/prompt': 0}
    assert result['process_tree_closed'] and result['native_exit_code_after_shutdown'] is not None
    assert result['accepted_initialize'] == (fault is None)
    assert result['faults'] == ([] if fault is None else [fault])
    assert result['retry_allowed'] is False
    if mode == 'timeout' and os.name == 'nt':
        pid = int((tmp_path / 'child.pid').read_text())
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            assert code.value != 259
