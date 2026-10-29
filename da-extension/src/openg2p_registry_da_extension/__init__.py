import sys as _sys

__version__ = "1.0.3"
__variant__ = "da"

# The celery worker imports this package (REGISTRY_EXTENSION_MODULE) but never
# runs the extension Initializer, and from platform 1.2 its own Initializer
# builds core's domain factory instead of ours. Build ours in every pool process
# once the worker is set up: it registers the platform components the worker
# leaves out and registers the DA import approval workflow service. Both steps are idempotent.
if "openg2p_registry_celery_worker" in _sys.modules:
    from celery.signals import worker_process_init as _worker_process_init

    @_worker_process_init.connect(weak=False)
    def _set_up_da_worker(**_kwargs):
        from .register_domain.factory import G2PRegisterDomainFactory

        G2PRegisterDomainFactory()
