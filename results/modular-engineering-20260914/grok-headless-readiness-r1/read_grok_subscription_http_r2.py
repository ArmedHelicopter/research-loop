"""Three official CLI-proxy GETs; no generation, refresh, login or writes."""
import hashlib
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
import urllib.error
import urllib.request

ROOT = Path('E:/_ryanDev/AI/research-loop-modular/work/grok-subscription-readonly-http-r2')
ROOT.mkdir(exist_ok=False)
AUTH = Path('C:/Users/Administrator/.grok/auth.json')
BASE = 'https://cli-chat-proxy.grok.com/v1'
record = {'schema': 'grok-cli-proxy-readonly-account-observation-v1',
    'observed_at': datetime.now(timezone.utc).isoformat(), 'requests': [],
    'model_requests': 0, 'credential_written': False, 'credential_hashed': False,
    'credential_source': 'existing-native-cli-login', 'redirects_permitted': False,
    'native_acp_receipt': False, 'generation_readiness_verified': False,
    'included_only_gate': None, 'fault': None}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
class Rejected(Exception):
    pass
def require(value, reason):
    if not value:
        raise Rejected(reason)
try:
    # Only a first-party OIDC login is considered; never an API-key entry.
    store = json.loads(AUTH.read_bytes())
    eligible = [v for v in store.values() if type(v) is dict and
        v.get('auth_mode') == 'oidc' and
        v.get('oidc_issuer') == 'https://auth.x.ai' and
        v.get('oidc_client_id') == 'b1a00492-073a-47ea-816f-4c329264a828']
    require(len(eligible) == 1, 'unique_native_oidc_login_unavailable')
    auth = eligible[0]
    require(datetime.fromisoformat(auth['expires_at'].replace('Z', '+00:00')) > datetime.now(timezone.utc), 'native_login_expired')
    require(all(type(auth.get(k)) is str and auth[k] and '\r' not in auth[k] and
        '\n' not in auth[k] for k in ('key', 'user_id')), 'native_login_shape')
    opener = urllib.request.build_opener(NoRedirect)
    payloads = []
    for name, route in (('credits', '/billing?format=credits'),
                        ('topup', '/auto-topup-rule'),
                        ('user', '/user?include=subscription')):
        request = urllib.request.Request(BASE + route, method='GET', headers={
            'Authorization': 'Bearer ' + auth['key'], 'X-XAI-Token-Auth': 'xai-grok-cli',
            'x-userid': auth['user_id'], 'x-grok-client-version': '1.0.13',
            'Accept': 'application/json'})
        row = {'name': name, 'url': BASE + route, 'method': 'GET', 'status': 'reserved'}
        record['requests'].append(row)
        (ROOT / 'receipt.json').write_text(json.dumps(record, sort_keys=True), encoding='utf-8')
        started = time.monotonic()
        try:
            with opener.open(request, timeout=10) as response:
                require(response.geturl() == BASE + route, 'redirected_request')
                raw = response.read(1048577)
                require(len(raw) <= 1048576, 'response_size')
                row['http_status'] = response.status
        except urllib.error.HTTPError as exc:
            row.update(status='http_error', http_status=exc.code)
            raise Rejected('official_readonly_endpoint_rejected') from None
        finally:
            row['elapsed_seconds'] = round(time.monotonic() - started, 3)
        (ROOT / (name + '.private.json')).write_bytes(raw)
        row.update(status='received', raw_sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        payload = json.loads(raw)
        require(type(payload) is dict, 'response_shape')
        payloads.append(payload)
    credits, topup, user = payloads
    require(user.get('userId') == auth['user_id'], 'account_binding')
    config = credits.get('config')
    require(type(config) is dict, 'credits_config')
    for field in ('onDemandCap', 'onDemandUsed', 'prepaidBalance'):
        value = config.get(field)
        require(type(value) is dict and set(value) <= {'val'}, 'money_shape')
        # Same protobuf Cent zero-value omission as the public native handler.
        require(type(value.get('val', 0)) is int and value.get('val', 0) == 0,
                'paid_balance_or_cap_available')
    require(config.get('isUnifiedBillingUser') is True, 'unified_subscription_unknown')
    require(topup == {} or topup == {'rule': None}, 'auto_topup_available_or_unknown')
    require(user.get('subscriptionTier') in ('SuperGrok', 'SuperGrokHeavy'), 'subscription_tier_unknown')
    period = config.get('currentPeriod')
    require(type(period) is dict, 'billing_period_unknown')
    now = datetime.now(timezone.utc)
    require(datetime.fromisoformat(period['start'].replace('Z', '+00:00')) <= now <
            datetime.fromisoformat(period['end'].replace('Z', '+00:00')), 'billing_period_stale')
    percent = config.get('creditUsagePercent')
    require(percent is None or type(percent) in (int, float) and 0 <= percent <= 100,
            'usage_percentage_shape')
    record['included_only_gate'] = {'unified_subscription': True,
        'on_demand_cap': 0, 'on_demand_used': 0, 'prepaid_balance': 0,
        'auto_topup_configured': False, 'account_binding': True,
        'subscription_tier': user['subscriptionTier'],
        'remaining_percentage': None if percent is None else 100 - percent,
        'atomic_per_request_spending_lock': False,
        'remote_on_demand_enabled_flag': 'not_observed',
        'observed_at': now.isoformat()}
except Rejected as exc:
    record['fault'] = str(exc)
except Exception as exc:
    # Do not log exception text, request headers, account IDs or credential data.
    record['fault'] = type(exc).__name__
(ROOT / 'receipt.json').write_text(json.dumps(record, sort_keys=True), encoding='utf-8')
print(json.dumps(record), flush=True)
