"""Loopback-only provider with real wire parsing and synthetic token accounting."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.helpers.calibration_pilot_fixture import fixture_target


class LocalProvider:
    def __init__(self, mode='normal', on_request=None):
        self.mode, self.on_request = mode, on_request
        self.calls = []; self.cap_checks = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                wire = self.rfile.read(int(self.headers['Content-Length']))
                b = json.loads(wire)
                owner.calls.append(b)
                if owner.on_request:
                    owner.on_request(b)
                assert self.path == '/v1/chat/completions'
                assert set(b) == {'model', 'messages', 'temperature', 'max_completion_tokens', 'stream', 'response_format'}
                assert b['response_format'] == {'type': 'json_object'} and b['stream'] is False
                cap = b['max_completion_tokens']; assert type(cap) is int and 1 <= cap <= 512
                owner.cap_checks += 1
                if owner.mode == 'timeout':
                    self.send_response(200); self.send_header('Content-Length', '1000'); self.end_headers()
                    self.wfile.write(b'{"PRIVATE_TIMEOUT_PARTIAL":'); self.wfile.flush()
                    time.sleep(1.4); return
                if owner.mode == 'http_error':
                    raw = b'{"PRIVATE_ERROR_SENTINEL":"rejected"}'
                    self.send_response(503); self.send_header('Content-Length', str(len(raw))); self.end_headers()
                    self.wfile.write(raw); return
                content = b['messages'][1]['content']
                review = 'state and dimensions' in b['messages'][0]['content']
                if review:
                    material = json.loads(content)
                    benchmark = 'blade' if 'cvars' in material['dimensions'] else 'discoverybench'
                    result = fixture_target(material['candidate']['answer'], benchmark)
                    if owner.mode == 'disagree' and b['model'].endswith('reviewer2'):
                        result = {'state': 'unknown', 'dimensions': None}
                else:
                    candidate = json.loads(content.split('\nANONYMOUS_CANDIDATE=', 1)[1])
                    benchmark = 'blade' if 'conceptual_variables' in content else 'discoverybench'
                    expected = fixture_target(candidate['answer'], benchmark)
                    dimensions = expected['dimensions']
                    if dimensions is None:
                        dimensions = fixture_target('known synthetic', benchmark)['dimensions']
                    result = {k: v * (2 if benchmark == 'blade' else 1) for k, v in dimensions.items()}
                    result['reason'] = 'synthetic local HTTP result'
                text = json.dumps(result)
                tokens = len(text.encode())
                reason = 'stop'
                if tokens > cap:
                    text = text.encode()[:cap].decode(errors='ignore'); tokens = cap; reason = 'length'
                if owner.mode == 'cap_breach':
                    tokens = cap + 1
                if owner.mode == 'invalid_content':
                    text = 'PRIVATE_INVALID_JSON'
                usage = {'prompt_tokens': len(wire), 'completion_tokens': tokens,
                    'total_tokens': len(wire) + tokens}
                if owner.mode == 'missing_usage':
                    usage = None
                response = {'id': 'same-provider-call' if owner.mode == 'duplicate' else 'local-' + str(len(owner.calls)),
                    'model': b['model'], 'choices': [{'index': 0, 'finish_reason': reason,
                        'message': {'role': 'assistant', 'content': text}}], 'usage': usage}
                raw = json.dumps(response).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f'http://127.0.0.1:{self.server.server_port}/v1/chat/completions'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
