from __future__ import annotations

from typing import Any

from opensign.contracts import DeviceProfile, FrameBundle

from .codec import CodecError, EncodedPayload, select_codec
from .codecs.coolledx import MODE_LEFT, map_user_scroll_speed
from .transport import BleakTransport, DryRunTransport, TransferResult


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
                ack_decoder=encoded.ack_decoder,
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
        # Transmitting never *requires* a verified profile: a controlled live
        # test is precisely how experimental evidence gets promoted to verified
        # (mirrors the live_* scripts, which always select with
        # allow_experimental=True). ``execute`` alone chooses a real write vs a
        # dry-run plan; a device codec that wants a stricter gate can enforce it.
        codec = select_codec(self.profile, allow_experimental=True)
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
        # See send_control: transmitting does not require verified status.
        codec = select_codec(self.profile, allow_experimental=True)
        encoded = codec.encode_frame_bundle(frame_bundle)
        return await self._deliver(
            encoded,
            execute=execute,
            retry_limit=retry_limit,
            timeout_seconds=timeout_seconds,
        )

    async def play_native_text(
        self,
        text: str,
        banner_rgb: bytes,
        banner_width: int,
        *,
        speed: int | float = 8,
        mode: int = MODE_LEFT,
        execute: bool = False,
        retry_limit: int = 3,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        """Upload a wide text banner and start firmware scroll on one BLE session.

        ``speed`` is the user-facing 0..10 scale (mapped to device byte 0..255).
        Sequence matches the verified experiment: banner (ack-paced) -> SPEED -> MODE.
        """
        codec = select_codec(self.profile, allow_experimental=True)
        encode_banner = getattr(codec, "encode_text_banner", None)
        if encode_banner is None:
            raise CodecError(
                f"codec {getattr(codec, 'name', type(codec).__name__)!r} does not support native text scroll"
            )

        speed_byte = map_user_scroll_speed(speed)
        banner = encode_banner(text, banner_rgb, banner_width)
        speed_ctrl = codec.encode_control("speed", speed_byte)
        mode_ctrl = codec.encode_control("mode", mode)

        transport: BleakTransport | DryRunTransport = (
            BleakTransport(self.profile, timeout_seconds=timeout_seconds)
            if execute
            else DryRunTransport(self.profile)
        )
        transfers: list[dict[str, Any]] = []
        try:
            banner_fc = banner.flow_control or {}
            banner_xfer = await transport.send_packets(
                banner.packets,
                retry_limit=retry_limit,
                await_ack=bool(banner_fc.get("await_ack", False)),
                ack_timeout=float(banner_fc.get("ack_timeout", 2.0)),
                ack_decoder=banner.ack_decoder,
            )
            transfers.append({"step": "banner", "transfer": _transfer_dict(banner_xfer)})

            for label, encoded in (("speed", speed_ctrl), ("mode", mode_ctrl)):
                xfer = await transport.send_packets(encoded.packets, retry_limit=retry_limit)
                transfers.append({"step": label, "transfer": _transfer_dict(xfer)})
        finally:
            if isinstance(transport, BleakTransport):
                await transport.disconnect()

        return {
            "encoded": {
                "banner": banner.to_dict(include_packet_hex=True),
                "speed": speed_ctrl.to_dict(include_packet_hex=True),
                "mode": mode_ctrl.to_dict(include_packet_hex=True),
            },
            "native_text": {
                "text": text,
                "banner_width": banner_width,
                "user_speed": speed,
                "device_speed": speed_byte,
                "mode": mode,
            },
            "transfers": transfers,
            "transfer": transfers[0]["transfer"] if transfers else {},
        }


def _transfer_dict(result: TransferResult) -> dict[str, Any]:
    return result.to_dict(include_chunk_hex=True)


class CoolLEDProtocol(ProtocolRuntime):
    """SeedScript-compatible facade name."""
