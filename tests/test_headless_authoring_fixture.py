"""Synthetic fixture expiry and the production transport expiry guard."""
from datetime import datetime, timezone
import json

import pytest

from research_loop.ontology import ContractError
import research_loop.modular.grok_headless_transport as transport
from tests.helpers.headless_authoring_fixture import (
    NATIVE_EXPIRY_GUARD,
    SYNTHETIC_AUTH_EXERCISE_WINDOW,
    synthetic_oidc_auth,
)


def _write_auth(home, body):
    home.mkdir()
    (home / 'auth.json').write_text(json.dumps(body), encoding='utf-8')


def test_synthetic_auth_remains_valid_at_a_24_hour_fixture_exercise_point(tmp_path, monkeypatch):
    origin = datetime(2030, 1, 1, tzinfo=timezone.utc)
    auth = synthetic_oidc_auth(origin)
    expiry = datetime.fromisoformat(auth['native']['expires_at'])
    assert expiry > origin + SYNTHETIC_AUTH_EXERCISE_WINDOW + NATIVE_EXPIRY_GUARD
    home = tmp_path / 'home'; _write_auth(home, auth)
    monkeypatch.setattr(transport.time, 'time', lambda: (origin + SYNTHETIC_AUTH_EXERCISE_WINDOW).timestamp())
    monkeypatch.setattr(transport.urllib.request, 'build_opener',
                        lambda *args: (_ for _ in ()).throw(AssertionError('network disabled in fixture boundary test')))
    with pytest.raises(AssertionError, match='network disabled'):
        transport._account_once(home, tmp_path / 'billing')


def test_transport_still_rejects_a_synthetic_login_inside_the_expiry_guard(tmp_path, monkeypatch):
    origin = datetime(2030, 1, 1, tzinfo=timezone.utc)
    auth = synthetic_oidc_auth(origin)
    auth['native']['expires_at'] = (origin + NATIVE_EXPIRY_GUARD).isoformat()
    home = tmp_path / 'home'; _write_auth(home, auth)
    monkeypatch.setattr(transport.time, 'time', lambda: origin.timestamp())
    monkeypatch.setattr(transport.urllib.request, 'build_opener',
                        lambda *args: (_ for _ in ()).throw(AssertionError('network must not be reached for expired auth')))
    with pytest.raises(ContractError, match='native login near expiry'):
        transport._account_once(home, tmp_path / 'billing')
