"""TEMPORARY overrides of OpenG2P platform behaviour, kept on the user's decision of 29 Oct 2026.

Each one replaces a method of a platform class in the running process, because
the platform offers no configuration or registration hook for it (checked on
registry-platform 1.2.2-rc.557: none of these classes is a registered
component, and none of the behaviours is a setting). The platform files on disk
are untouched. Every override is idempotent and skips cleanly when the platform
package it targets is not in the process. Remove each one when OpenG2P fixes
it; docs/refactor/platform-overrides.md lists them with the re-check steps.

A fourth override (FilterBuilder accepting "true"/"false" strings) was removed
on 29 Oct 2026: no DA filter is boolean (register metadata and the platform
define none), so it never applied.

Everything else this extension changes in the platform goes through the
component registry (subclass registered ahead of the platform service); this
module is the only place that reassigns platform methods.

1. IAM permission lookup (staff API) - install_scoped_permission_lookup
   Bug: the platform asks IAM `get_permissions_for_roles` with bare role names,
   and IAM answers with the first active role of that name across every
   registered application. On a cluster hosting several registries the roles
   share names, so a user's permissions come from whichever application sorts
   first. The override asks `get_application_permissions_for_user` for this
   application only.
   Platform version checked: 1.2.2-rc.557.
   Without it: users get another registry's permissions (too many or too few).
   Remove when OpenG2P fixes it.

2. Celery worker database engine - install_worker_null_pool
   Bug: one pooled async engine per process, but each task module runs on its
   own event loop; asyncpg binds a connection to the loop it was opened on, so
   a pooled connection handed from one task type to another fails with
   "attached to a different loop" and valid records get stuck behind an invalid
   one. The platform exposes pool size settings but no NullPool setting. The
   override opens a fresh connection per session.
   Platform version checked: 1.2.2-rc.557 (the error still shows on first
   attempts there; rows are retried and complete).
   Without it: imports stall or fail more often on that error.
   Remove when OpenG2P fixes it.

3. DataPolicyMiddleware own-record policy - install_own_record_data_policy
   Gap: the platform's data policies are role-based lists; there is no
   per-user, claim-based policy. For a Development Agent (token claim `da_id`,
   only the Data Editor role) the override replaces the request's policies with
   one ALLOW policy on their own DA record (da_own_record.py holds the rules).
   The middleware is added by the platform's app module, so it cannot be
   subclassed from an extension.
   Platform version checked: 1.2.2-rc.557.
   Without it: a Development Agent sees records of the Woreda or Region their
   roles allow instead of only their own.
   Remove when OpenG2P fixes it (per-user data policies).
"""

import contextvars
import functools
import logging

_logger = logging.getLogger("da-temporary-platform-overrides")
_INSTALLED = "_da_platform_override"

# ------------------------------------------------------------ 1. permissions

_current_request: contextvars.ContextVar = contextvars.ContextVar("da_current_request", default=None)


def permissions_for_application(applications, client_id: str) -> set[str]:
    """The permissions IAM reports for this client only."""
    permissions: set[str] = set()
    for application in applications or []:
        if (application or {}).get("application_mnemonic") == client_id:
            permissions.update(application.get("permissions") or [])
    return permissions


def install_scoped_permission_lookup() -> bool:
    try:
        import httpx
        from iam_core.user_auth.middleware.resolve_permissions import ResolvePermissionMiddleware
        from openg2p_fastapi_common.errors.http_exceptions import ForbiddenError
    except ImportError:
        return False
    if getattr(ResolvePermissionMiddleware.dispatch, _INSTALLED, False):
        return True

    original_dispatch = ResolvePermissionMiddleware.dispatch
    original_fetch = ResolvePermissionMiddleware._fetch_permissions_for_roles

    @functools.wraps(original_dispatch)
    async def dispatch(self, request, call_next):
        token = _current_request.set(request)
        try:
            return await original_dispatch(self, request, call_next)
        finally:
            _current_request.reset(token)

    @functools.wraps(original_fetch)
    async def _fetch_permissions_for_roles(self, role_mnemonics):
        auth_provider_api_url = (self._config.auth_provider_api_url or "").strip()
        if not auth_provider_api_url:
            raise ForbiddenError(message="Forbidden. auth_provider_api_url is not configured.")
        if not role_mnemonics:
            return set()
        request = _current_request.get()
        principal = getattr(request.state, self._state_key, None) if request is not None else None
        client_id = (self._client_id or "").strip()
        credentials = getattr(principal, "credentials", None)
        if not credentials or not client_id:
            raise ForbiddenError(message="Forbidden. Unable to fetch user permissions.")
        endpoint = auth_provider_api_url.rstrip("/") + "/user-access/get_application_permissions_for_user"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    endpoint,
                    params={"application_mnemonic": client_id},
                    headers={"Authorization": f"Bearer {credentials}"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ForbiddenError(message="Forbidden. Unable to fetch user permissions.") from exc
        return permissions_for_application(response.json(), client_id)

    setattr(dispatch, _INSTALLED, True)
    setattr(_fetch_permissions_for_roles, _INSTALLED, True)
    ResolvePermissionMiddleware.dispatch = dispatch
    ResolvePermissionMiddleware._fetch_permissions_for_roles = _fetch_permissions_for_roles
    _logger.info("IAM permissions resolved per application (platform cross-registry lookup fix)")
    return True


# ----------------------------------------------------------------- 2. worker


def install_worker_null_pool() -> bool:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        from openg2p_registry_celery_worker.engine import Engine
    except ImportError:
        return False
    if getattr(Engine.get_async_engine, _INSTALLED, False):
        return True

    def get_async_engine():
        if Engine._async_engine is None:
            datasource = Engine.construct_async_db_datasource()
            try:
                Engine._async_engine = create_async_engine(datasource, poolclass=NullPool)
            except Exception as e:  # same message as the platform's
                raise ValueError(f"Invalid DB datasource: {datasource} | ERROR: {e}")
        return Engine._async_engine

    setattr(get_async_engine, _INSTALLED, True)
    Engine.get_async_engine = staticmethod(get_async_engine)
    _logger.info("Celery worker async engine uses NullPool (platform event-loop fix)")
    return True


# ------------------------------------------------- 3. own-record data policy


def install_own_record_data_policy() -> bool:
    try:
        from iam_core.user_auth.middleware.data_policy import DataPolicyMiddleware
    except ImportError:
        return False
    if getattr(DataPolicyMiddleware.dispatch, _INSTALLED, False):
        return True
    from .services.da_own_record import apply_self_policy

    original_dispatch = DataPolicyMiddleware.dispatch

    @functools.wraps(original_dispatch)
    async def dispatch(self, request, call_next):
        async def call_next_with_self_policy(req):
            try:
                await apply_self_policy(req, self.policies_state_key, self.auth_state_key)
            except Exception:  # never block a request because of the guard itself
                _logger.exception("DA self-service policy could not be applied")
            return await call_next(req)

        return await original_dispatch(self, request, call_next_with_self_policy)

    setattr(dispatch, _INSTALLED, True)
    DataPolicyMiddleware.dispatch = dispatch
    _logger.info("DataPolicyMiddleware applies the Development Agent own-record policy (platform workaround)")
    return True


def install_temporary_platform_overrides() -> None:
    install_scoped_permission_lookup()
    install_worker_null_pool()
    install_own_record_data_policy()
