from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Iterable

from opensign.contracts import DeviceProfile

from .packet import Chunk, chunk_packets


class TransportError(RuntimeError):
    """Raised when BLE transport cannot complete a guarded operation."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _classify_ack(
    notification_hex: str | None,
    decoder: Callable[[bytes], dict[str, Any]] | None,
) -> dict[str, Any]:
    """Interpret a device notification as an ack via an optional codec decoder.

    Without a decoder the transport is device-agnostic and can only say a
    notification *arrived* (``status=None``), which the caller counts as an ack.
    With a codec decoder it distinguishes an explicit success from a checksum
    error / NAK so an unverified transfer is never mislabelled ack-verified.
    """
    if decoder is None:
        return {"index": None, "status": None, "is_success": True, "is_nak": False}
    try:
        data = bytes.fromhex(notification_hex or "")
    except ValueError:
        data = b""
    return decoder(data)


@dataclass(slots=True)
class TransferResult:
    success: bool
    dry_run: bool
    packet_count: int
    chunks: list[Chunk]
    bytes_sent: int
    attempts: int
    notifications: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=_now)
    completed_at: str | None = None
    chunk_size: int | None = None
    chunk_size_source: str | None = None
    display_verification: str = "not_observed"
    awaited_ack: bool = False
    acks_received: int = 0
    ack_timeouts: int = 0
    naks: int = 0
    nak_retries: int = 0

    def to_dict(self, *, include_chunk_hex: bool = True) -> dict[str, Any]:
        chunks = [chunk.to_dict() for chunk in self.chunks]
        if not include_chunk_hex:
            for item in chunks:
                item.pop("hex", None)
        return {
            "success": self.success,
            "dry_run": self.dry_run,
            "packet_count": self.packet_count,
            "chunk_count": len(self.chunks),
            "bytes_sent": self.bytes_sent,
            "attempts": self.attempts,
            "notifications": list(self.notifications),
            "errors": list(self.errors),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "chunk_size": self.chunk_size,
            "chunk_size_source": self.chunk_size_source,
            "display_verification": self.display_verification,
            "awaited_ack": self.awaited_ack,
            "acks_received": self.acks_received,
            "ack_timeouts": self.ack_timeouts,
            "naks": self.naks,
            "nak_retries": self.nak_retries,
            "chunks": chunks,
        }


def conservative_chunk_size(profile: DeviceProfile) -> tuple[int, str]:
    configured = profile.connection.get("maximum_chunk_size")
    if isinstance(configured, int) and configured > 0:
        return configured, "device_profile"
    mtu = profile.connection.get("mtu")
    if isinstance(mtu, int) and mtu > 3:
        return mtu - 3, "profile_mtu_minus_att_header"
    return 20, "conservative_ble_default"


class DryRunTransport:
    def __init__(self, profile: DeviceProfile):
        self.profile = profile

    async def send_packets(
        self,
        packets: Iterable[bytes],
        *,
        retry_limit: int = 3,
        await_ack: bool = False,
        ack_timeout: float = 2.0,
        ack_decoder: Callable[[bytes], dict[str, Any]] | None = None,
        nak_retry_limit: int = 2,
    ) -> TransferResult:
        packet_list = [bytes(packet) for packet in packets]
        chunk_size, source = conservative_chunk_size(self.profile)
        delay = float(self.profile.connection.get("inter_chunk_delay_ms", 0))
        chunks = chunk_packets(packet_list, chunk_size, delay_ms=delay)
        result = TransferResult(
            success=True,
            dry_run=True,
            packet_count=len(packet_list),
            chunks=chunks,
            bytes_sent=sum(len(chunk.data) for chunk in chunks),
            attempts=len(chunks),
            chunk_size=chunk_size,
            chunk_size_source=source,
            awaited_ack=await_ack,
        )
        result.completed_at = _now()
        return result


class BleakTransport:
    """One-session BLE writer driven only by the active device profile."""

    def __init__(self, profile: DeviceProfile, *, timeout_seconds: float = 15.0):
        self.profile = profile
        self.timeout_seconds = timeout_seconds
        self.client: Any = None
        self.write_characteristic_object: Any = None
        self.notifications: list[dict[str, Any]] = []
        self.notify_subscribed = False
        self._notify_event = asyncio.Event()

    async def connect(self) -> None:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as exc:  # pragma: no cover
            raise TransportError("Bleak is required for physical BLE delivery") from exc

        device_id = self.profile.require_device_id()
        write_uuid = self.profile.require_write_characteristic()
        device: Any = None
        finder = getattr(BleakScanner, "find_device_by_address", None)
        if finder is not None:
            try:
                device = await finder(device_id, timeout=self.timeout_seconds)
            except Exception:
                device = None
        target = device if device is not None else device_id
        self.client = BleakClient(target, timeout=self.timeout_seconds)
        await self.client.connect()
        if not self.client.is_connected:
            raise TransportError(f"Failed to connect to {device_id}")

        self.write_characteristic_object = self.client.services.get_characteristic(write_uuid)
        if self.write_characteristic_object is None:
            await self.disconnect()
            raise TransportError(f"Configured write characteristic not found: {write_uuid}")

        notify_uuid = self.profile.notify_characteristic
        if notify_uuid:
            notify_object = self.client.services.get_characteristic(notify_uuid)
            if notify_object is None:
                await self.disconnect()
                raise TransportError(f"Configured notify characteristic not found: {notify_uuid}")

            def on_notification(sender: Any, data: bytearray) -> None:
                self.notifications.append(
                    {
                        "timestamp": _now(),
                        "sender": str(getattr(sender, "uuid", sender)),
                        "hex": bytes(data).hex(),
                        "length": len(data),
                    }
                )
                self._notify_event.set()

            await self.client.start_notify(notify_object, on_notification)
            self.notify_subscribed = True

    async def disconnect(self) -> None:
        if self.client is not None:
            try:
                if self.profile.notify_characteristic and self.client.is_connected:
                    try:
                        await self.client.stop_notify(self.profile.notify_characteristic)
                    except Exception:
                        pass
                if self.client.is_connected:
                    await self.client.disconnect()
            finally:
                self.client = None
                self.write_characteristic_object = None
                self.notify_subscribed = False

    def _chunk_size(self) -> tuple[int, str]:
        configured = self.profile.connection.get("maximum_chunk_size")
        if isinstance(configured, int) and configured > 0:
            return configured, "device_profile"
        if (
            not self.profile.connection.get("write_with_response", False)
            and self.write_characteristic_object is not None
        ):
            try:
                size = int(self.write_characteristic_object.max_write_without_response_size)
                if size > 0:
                    return size, "bleak_characteristic_limit"
            except Exception:
                pass
        if self.client is not None:
            try:
                mtu = int(self.client.mtu_size)
                if mtu > 3:
                    return mtu - 3, "negotiated_mtu_minus_att_header"
            except Exception:
                pass
        return 20, "conservative_ble_default"

    async def _await_notification(self, baseline: int, timeout: float) -> bool:
        """Wait until a new device notification arrives past ``baseline`` count.

        Returns True if a notification was observed within ``timeout`` seconds.
        The notify callback appends then sets the event, so re-checking the count
        after clearing avoids missing an ack that arrives during the wait setup.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max(timeout, 0.0)
        while len(self.notifications) <= baseline:
            self._notify_event.clear()
            if len(self.notifications) > baseline:
                return True
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(self._notify_event.wait(), timeout=remaining)
            except (asyncio.TimeoutError, TimeoutError):
                return len(self.notifications) > baseline
        return True

    async def send_packets(
        self,
        packets: Iterable[bytes],
        *,
        retry_limit: int = 3,
        await_ack: bool = False,
        ack_timeout: float = 2.0,
        ack_decoder: Callable[[bytes], dict[str, Any]] | None = None,
        nak_retry_limit: int = 2,
    ) -> TransferResult:
        if retry_limit < 0:
            raise ValueError("retry_limit cannot be negative")
        if nak_retry_limit < 0:
            raise ValueError("nak_retry_limit cannot be negative")
        packet_list = [bytes(packet) for packet in packets]
        if self.client is None or not self.client.is_connected:
            await self.connect()
        chunk_size, source = self._chunk_size()
        delay = float(self.profile.connection.get("inter_chunk_delay_ms", 0))
        response = bool(self.profile.connection.get("write_with_response", False))
        chunks = chunk_packets(packet_list, chunk_size, delay_ms=delay)
        chunks_by_packet: dict[int, list[Chunk]] = {}
        for chunk in chunks:
            chunks_by_packet.setdefault(chunk.packet_index, []).append(chunk)
        pace_acks = await_ack and self.notify_subscribed
        notify_start = len(self.notifications)
        result = TransferResult(
            success=False,
            dry_run=False,
            packet_count=len(packet_list),
            chunks=chunks,
            bytes_sent=0,
            attempts=0,
            chunk_size=chunk_size,
            chunk_size_source=source,
            awaited_ack=pace_acks,
        )

        async def _write_chunk(chunk: Chunk) -> str | None:
            last_error: Exception | None = None
            for attempt in range(retry_limit + 1):
                result.attempts += 1
                try:
                    await self.client.write_gatt_char(
                        self.write_characteristic_object,
                        chunk.data,
                        response=response,
                    )
                    result.bytes_sent += len(chunk.data)
                    return None
                except Exception as exc:
                    last_error = exc
                    if attempt < retry_limit:
                        await asyncio.sleep(max(delay / 1000.0, 0.01))
            return f"{type(last_error).__name__}:{last_error}"

        try:
            for packet_index in range(len(packet_list)):
                packet_chunks = chunks_by_packet.get(packet_index, [])
                # A decoded checksum-error (NAK) re-sends the whole packet up to
                # nak_retry_limit; a decoded success -- or a bare notification when
                # no decoder is supplied -- completes it.
                for attempt in range(nak_retry_limit + 1):
                    ack_baseline = len(self.notifications)
                    for chunk in packet_chunks:
                        error = await _write_chunk(chunk)
                        if error is not None:
                            result.errors.append(
                                f"packet={chunk.packet_index} chunk={chunk.chunk_index}: {error}"
                            )
                            return result
                    if not pace_acks:
                        if delay > 0:
                            await asyncio.sleep(delay / 1000.0)
                        break
                    # Wait for the device's per-packet ack before the next packet so
                    # we don't overrun its receive buffer. A missing ack is a soft
                    # signal (ack_timeouts): every byte was still written.
                    if not await self._await_notification(ack_baseline, ack_timeout):
                        result.ack_timeouts += 1
                        break
                    ack = _classify_ack(self.notifications[-1].get("hex"), ack_decoder)
                    if ack["is_nak"] and attempt < nak_retry_limit:
                        result.nak_retries += 1
                        continue
                    if ack["is_nak"]:
                        result.naks += 1
                    elif ack["is_success"] or ack["status"] is None:
                        result.acks_received += 1
                    break
            result.success = not result.errors
            return result
        finally:
            result.notifications = list(self.notifications[notify_start:])
            result.completed_at = _now()
