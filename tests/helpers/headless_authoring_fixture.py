"""Exercise the real transport/account parser using synthetic HTTP and processes."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from research_loop.modular.grok_acp_transport import ProcessTree
from evaluation.modular.diagnostic_subscription import sha
import research_loop.modular.grok_headless_transport as transport


# The complete synthetic C5 controller can exceed two hours.  Keep this
# fixture-only credential valid for a bounded four-hour integration window
# plus the production transport's 120-second near-expiry guard.
SYNTHETIC_FULL_C5_WINDOW = timedelta(hours=4)
SYNTHETIC_AUTH_VALIDITY = timedelta(hours=6)
NATIVE_EXPIRY_GUARD = timedelta(seconds=120)


def synthetic_oidc_auth(now=None):
    now = datetime.now(timezone.utc) if now is None else now
    return {'native': {'auth_mode': 'oidc', 'oidc_issuer': 'https://auth.x.ai',
        'oidc_client_id': 'b1a00492-073a-47ea-816f-4c329264a828',
        'key': 'PRIVATE_SYNTHETIC_NATIVE_TOKEN', 'user_id': 'synthetic-account',
        'expires_at': (now + SYNTHETIC_AUTH_VALIDITY).isoformat()}}


def install_synthetic_native(monkeypatch, envelope):
    deployment = envelope['native_deployment']; calls = []; gets = []
    monkeypatch.setattr(transport, 'EXECUTABLE_SHA256', sha(deployment['executable']))
    auth = synthetic_oidc_auth()
    for slot in deployment['slots'].values():
        (Path(slot['private_home']) / 'auth.json').write_text(json.dumps(auth), encoding='utf-8')
    peer = Path(__file__).resolve().parents[1] / 'fixtures' / 'headless_authoring_peer.py'

    def spawn(command, cwd, env, stderr):
        assert env['GROK_DISABLE_API_KEY_AUTH'] == '1'
        if 'inspect' in command:
            args = ['inspect']
        else:
            calls.append(command)
            args = [command[command.index('--session-id') + 1], command[command.index('--prompt-file') + 1]]
        return ProcessTree([sys.executable, str(peer), *args], cwd=cwd, env=env, stderr=stderr)

    class Response:
        status = 200
        def __init__(self, request):
            self.url = request.full_url; gets.append(self.url)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return self.url
        def read(self, maximum):
            now = datetime.now(timezone.utc)
            if self.url.endswith('/billing?format=credits'):
                body = {'config': {'isUnifiedBillingUser': True, 'onDemandCap': {}, 'onDemandUsed': {},
                    'prepaidBalance': {}, 'on_demand_enabled': False, 'creditUsagePercent': 2,
                    'currentPeriod': {'start': (now-timedelta(days=1)).isoformat(),
                        'end': (now+timedelta(days=1)).isoformat()}}}
            elif self.url.endswith('/auto-topup-rule'):
                body = {}
            else:
                assert self.url.endswith('/user?include=subscription')
                body = {'userId': 'synthetic-account', 'hasGrokCodeAccess': True,
                    'userBlockedReason': None, 'teamBlockedReasons': [], 'subscriptionTier': 'GrokPro'}
            return json.dumps(body).encode()

    class Opener:
        def open(self, request, timeout): return Response(request)

    monkeypatch.setattr(transport, 'ProcessTree', spawn)
    monkeypatch.setattr(transport.urllib.request, 'build_opener', lambda *handlers: Opener())
    return calls, gets
