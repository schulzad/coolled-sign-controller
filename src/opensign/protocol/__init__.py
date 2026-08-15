"""Profile-driven codecs, packet chunking, and guarded BLE transport."""

# Importing the plugin package registers bundled device codecs (e.g. "coolledx")
# with the codec registry so select_codec can resolve them from a profile.
from . import codecs as codecs  # noqa: E402
from .codec import CodecError, select_codec
from .runtime import CoolLEDProtocol, ProtocolRuntime

__all__ = ["CodecError", "CoolLEDProtocol", "ProtocolRuntime", "codecs", "select_codec"]
