"""Removed runner sandbox namespace.

Sandbox receipt implementation is owned by the host-protocol boundary and is
exposed to current workflow code through ``workflow.sandbox_receipts``. The
former runner namespace remains an empty import boundary for major-version
diagnostics; it must not reintroduce a dependency on active workflow code.
"""

__all__: tuple[str, ...] = ()
