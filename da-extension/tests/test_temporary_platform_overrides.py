"""Temporary in-process workarounds for platform gaps (temporary_platform_overrides.py).

Each test skips when the platform package it targets is not installed in the
process running the tests (the worker fix needs the celery image); the staff-API image covers the IAM one.
"""

import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest

# The platform's partner-API and worker packages import the extension through
# the alias that their container entrypoint creates; create it here too.
sys.modules.setdefault("openg2p_registry_extensions", importlib.import_module("openg2p_registry_da_extension"))

from openg2p_registry_da_extension.register_domain import temporary_platform_overrides as po


def test_permissions_for_application_keeps_only_this_client():
    payload = [
        {"application_mnemonic": "farmer-registry-staff-portal", "permissions": ["register:view", "register:export"]},
        {"application_mnemonic": "da-registry-staff-portal", "permissions": ["register:view", "changeRequest:create"]},
        None,
    ]
    assert po.permissions_for_application(payload, "da-registry-staff-portal") == {"register:view", "changeRequest:create"}
    assert po.permissions_for_application(payload, "unknown") == set()
    assert po.permissions_for_application(None, "x") == set()


def test_permission_lookup_is_scoped_to_this_application(monkeypatch):
    pytest.importorskip("iam_core")
    import httpx
    from iam_core.user_auth.middleware.resolve_permissions import ResolvePermissionMiddleware

    assert po.install_scoped_permission_lookup() is True
    assert po.install_scoped_permission_lookup() is True  # idempotent
    calls = {}

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self):
            return [{"application_mnemonic": "other-portal", "permissions": ["a:b"]},
                    {"application_mnemonic": "da-registry-staff-portal", "permissions": ["register:view"]}]

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, headers=None):
            calls.update(url=url, params=params, headers=headers); return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    middleware = ResolvePermissionMiddleware(app=None, client_id="da-registry-staff-portal")
    middleware._config = SimpleNamespace(auth_provider_api_url="http://iam:8000")
    request = SimpleNamespace(state=SimpleNamespace(auth=SimpleNamespace(credentials="tok-123")))
    token = po._current_request.set(request)
    try:
        permissions = asyncio.run(middleware._fetch_permissions_for_roles(["Data Editor"]))
    finally:
        po._current_request.reset(token)
    assert permissions == {"register:view"}
    assert calls["url"].endswith("/user-access/get_application_permissions_for_user")
    assert calls["params"] == {"application_mnemonic": "da-registry-staff-portal"}
    assert calls["headers"] == {"Authorization": "Bearer tok-123"}


def test_data_policy_middleware_applies_the_own_record_policy():
    pytest.importorskip("iam_core")
    from iam_core.user_auth.middleware.data_policy import DataPolicyMiddleware

    assert po.install_own_record_data_policy() is True
    assert po.install_own_record_data_policy() is True  # idempotent
    assert getattr(DataPolicyMiddleware.dispatch, po._INSTALLED) is True
