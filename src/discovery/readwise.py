"""Readwise Reader integration — re-exported from local_first_common.

The implementation lives in discovery.support.readwise.
This module exists for backwards compatibility with callers inside
this package that import from discovery.readwise.

Note: discovery.support.readwise uses (token, url) argument order.
The orchestrator call sites already pass positional args in this order.
"""

from discovery.support.readwise import save_to_readwise

__all__ = ["save_to_readwise"]
