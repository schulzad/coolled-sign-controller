from __future__ import annotations

from typing import Any

from opensign.contracts import DeviceProfile, FrameBundle

from .codec import EncodedPayload, select_codec
from .transport import BleakTransport, DryRunTransport


class ProtocolRuntime:
    """Profile-aware control and frame-delivery facade."""

    def __init__(self, profile: DeviceProfile | dict[str, Any]):
        self.profile = profile if isinstance(profile, DeviceProfile) else DeviceProfile(profile)

    async def _deliver(
        self,
        encoded: EncodedPayload,
        *,
        execute: bool,
        retry_limit: int,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        transport = (
            BleakTransport(self.profile, timeout_seconds=timeout_seconds)
            if execute
            else DryRunTransport(self.profile)
        )
        flow_control = encoded.flow_control or {}
        await_ack = bool(flow_control.get("await_ack", False))
        ack_timeout = float(flow_control.get("ack_timeout", 2.0))
        try:
            transfer = await transport.send_packets(
                encoded.packets,
                retry_limit=retry_limit,
                await_ack=await_ack,
                ack_timeout=ack_timeout,
            )
        finally:
            if isinstance(transport, BleakTransport):
                await transport.disconnect()
        return {
            "encoded": encoded.to_dict(include_packet_hex=True),
            "transfer": transfer.to_dict(include_chunk_hex=True),
        }

    async def send_control(
        self,
        command: str,
        value: Any = None,
        *,
        execute: bool = False,
        retry_limit: int = 3,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        codec = select_codec(self.profile, allow_experimental=not execute)
        encoded = codec.encode_control(command, value)
        return await self._deliver(
            encoded,
            execute=execute,
            retry_limit=retry_limit,
            timeout_seconds=timeout_seconds,
        )

    async def upload_frame_bundle(
        self,
        frame_bundle: FrameBundle,
        *,
        execute: bool = False,
        retry_limit: int = 3,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        codec = select_codec(self.profile, allow_experimental=not execute)
        encoded = codec.encode_frame_bundle(frame_bundle)
        return await self._deliver(
            encoded,
            execute=execute,
            retry_limit=retry_limit,
            timeout_seconds=timeout_seconds,
        )


class CoolLEDProtocol(ProtocolRuntime):
    """SeedScript-compatible facade name."""
