"""Device-specific codec plugins.

Importing this package registers each bundled plugin with the protocol codec
registry so that ``select_codec`` can resolve a profile's ``protocol.codec``
name (e.g. ``"coolledx"``).
"""

from __future__ import annotations

from . import coolledx as coolledx

__all__ = ["coolledx"]
