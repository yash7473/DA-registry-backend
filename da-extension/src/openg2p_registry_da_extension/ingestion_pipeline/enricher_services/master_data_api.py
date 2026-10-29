"""Master Data, read through its API by the DA import enrichers.

The enrichers run synchronously inside the celery transformation worker, so
this is a small synchronous client for the same calls the platform's own
Master Data client makes (openg2p_registry_core.helpers.master_data): a
client-credentials token for the worker's Keycloak client, the request
envelope, `/attributes/get_attribute_values` for code lists and
`/geo/get_all_geo_levels` + `/geo/get_geo_level_values` (one call per level)
for the geography, kept in an in-process cache for a few minutes.

Settings are the worker's platform settings (env), so there is nothing extra
to configure:
  REGISTRY_CELERY_WORKERS_MASTER_DATA_API_URL
  REGISTRY_CELERY_WORKERS_MASTER_DATA_TOKEN_URL
  REGISTRY_CELERY_WORKERS_MASTER_DATA_CLIENT_ID
  REGISTRY_CELERY_WORKERS_MASTER_DATA_CLIENT_SECRET
(the partner and staff API prefixes are read as a fallback, so the module also
works in those processes).
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

PREFIXES = ("REGISTRY_CELERY_WORKERS_", "REGISTRY_PARTNER_API_", "REGISTRY_STAFF_PORTAL_API_")
CACHE_SECONDS = 300
TIMEOUT_SECONDS = 30.0

_lock = threading.Lock()
_token: tuple[float, str] | None = None      # (expires, access token)
_geo: tuple[float, dict[str, dict]] | None = None  # (expires, level_value_id -> node)


class MasterDataUnavailable(RuntimeError):
    """Master Data could not be reached or answered with an error."""


def setting(name: str) -> str:
    for prefix in PREFIXES:
        value = (os.environ.get(f"{prefix}MASTER_DATA_{name}") or "").strip()
        if value:
            return value
    return ""


def _access_token(client: httpx.Client) -> str | None:
    global _token
    token_url, client_id = setting("TOKEN_URL"), setting("CLIENT_ID")
    if not token_url or not client_id:
        return None
    with _lock:
        if _token and _token[0] > time.monotonic():
            return _token[1]
    resp = client.post(token_url, data={
        "grant_type": "client_credentials", "client_id": client_id, "client_secret": setting("CLIENT_SECRET"),
    })
    if resp.status_code != 200:
        raise MasterDataUnavailable(f"Keycloak refused the Master Data token ({resp.status_code})")
    body = resp.json()
    if not body.get("access_token"):
        raise MasterDataUnavailable("Keycloak answered without an access token for Master Data")
    with _lock:
        _token = (time.monotonic() + max(int(body.get("expires_in") or 60) - 30, 10), body["access_token"])
    return _token[1]


def post(path: str, payload: dict[str, Any] | None = None, pagination: dict[str, Any] | None = None) -> Any:
    """The response_payload of a Master Data API call."""
    global _token
    base = setting("API_URL").rstrip("/")
    if not base:
        raise MasterDataUnavailable("Master Data API is not configured (REGISTRY_CELERY_WORKERS_MASTER_DATA_API_URL)")
    envelope = {
        "request_header": {
            "request_id": uuid.uuid4().hex, "request_timestamp": datetime.now(timezone.utc).isoformat(),
            "sender_app_mnemonic": "da-registry", "sender_app_url": "http://da-registry",
        },
        "request_body": {"request_payload": payload or {}, "pagination_request": pagination},
    }
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            token = _access_token(client)
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            resp = client.post(base + path, json=envelope, headers=headers)
            if resp.status_code == 401 and token:
                with _lock:
                    _token = None
                token = _access_token(client)
                resp = client.post(base + path, json=envelope, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise MasterDataUnavailable(f"Master Data API {path}: {exc}") from exc
    if resp.status_code != 200:
        raise MasterDataUnavailable(f"Master Data API {path} answered {resp.status_code}")
    body = resp.json()
    header = body.get("response_header") or {}
    if header.get("response_status") == "ERROR":
        raise MasterDataUnavailable(f"Master Data API {path}: {header.get('response_error_message') or 'error'}")
    return (body.get("response_body") or {}).get("response_payload")


def geo_index() -> dict[str, dict]:
    """{level_value_id: {level_value_id, level_value_mnemonic, parent_level_value_id,
    level_id, level_mnemonic}} for every unit, cached."""
    global _geo
    with _lock:
        if _geo and _geo[0] > time.monotonic():
            return _geo[1]
    levels = post("/geo/get_all_geo_levels") or []
    index: dict[str, dict] = {}
    for level in levels if isinstance(levels, list) else []:
        level_id = (level or {}).get("level_id")
        if not level_id:
            continue
        mnemonic = level.get("level_mnemonic") or ""
        rows = post("/geo/get_geo_level_values", {"level_id": level_id, "parent_level_value_id": None}) or []
        for row in rows if isinstance(rows, list) else []:
            value_id = (row or {}).get("level_value_id")
            if value_id:
                index[value_id] = {
                    "level_value_id": value_id,
                    "level_value_mnemonic": row.get("level_value_mnemonic") or "",
                    "parent_level_value_id": row.get("parent_level_value_id") or None,
                    "level_id": row.get("level_id") or level_id,
                    "level_mnemonic": mnemonic,
                }
    with _lock:
        _geo = (time.monotonic() + CACHE_SECONDS, index)
    return index


def invalidate() -> None:
    global _token, _geo
    with _lock:
        _token = None
        _geo = None
