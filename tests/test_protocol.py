import asyncio
import io

import pytest
from PIL import Image

import opensign.protocol  # noqa: F401  (registers bundled device codecs)
from opensign.animation.studio import PixelAnimationStudio
from opensign.contracts import DeviceProfile, FrameBundle, default_device_profile
from opensign.protocol.codec import CodecError, apply_checksum, render_hex_template, select_codec
from opensign.protocol.packet import chunk_payload
from opensign.protocol.transport import BleakTransport


def literal_profile(*, status: str = "experimental") -> DeviceProfile:
    data = default_device_profile()
    data["protocol"] = {
        "codec": "profile_literal",
        "status": status,
        "encryption": {"mode": "none"},
        "commands": {
            "brightness": {
                "status": status,
                "replay_safe": status == "verified",
                "template_hex": "AA {value_u8} 55",
                "value_scale": {
                    "input_min": 0,
                    "input_max": 100,
                    "output_min": 0,
                    "output_max": 255,
                },
                "checksum": {"algorithm": "sum8"},
                "evidence": ["capture-1"],
            }
        },
        "frame_transfer": {
            "status": status,
            "replay_safe": status == "verified",
            "mode": "per_frame_template",
            "input_color_mode": "rgb888",
            "packet_template_hex": "F0 {frame_index_u8} {frame_length_u16le} {frame_hex} 0F",
            "evidence": ["capture-frames"],
        },
    }
    return DeviceProfile(data)


def test_restricted_hex_template() -> None:
    packet = render_hex_template(
        "AA {frame_index_u8} {frame_length_u16le} {frame_hex} 55",
        {"frame_index": 2, "frame_length": 3, "frame": b"\x01\x02\x03"},
    )
    assert packet == bytes.fromhex("AA 02 03 00 01 02 03 55")


def test_checksum_helpers() -> None:
    assert apply_checksum(bytes.fromhex("01 02"), {"algorithm": "sum8"}) == bytes.fromhex("01 02 03")
    assert apply_checksum(bytes.fromhex("01 02"), {"algorithm": "xor8"}) == bytes.fromhex("01 02 03")


def test_experimental_profile_can_dry_run_encode() -> None:
    codec = select_codec(literal_profile(), allow_experimental=True)
    encoded = codec.encode_control("brightness", 50)
    assert encoded.packets[0] == bytes.fromhex("AA 80 55 7F")
    assert encoded.metadata["value_encoded"] == 128


def test_experimental_profile_cannot_be_selected_for_physical_execution() -> None:
    with pytest.raises(CodecError):
        select_codec(literal_profile(), allow_experimental=False)


def test_verified_profile_encodes_frame_bundle() -> None:
    codec = select_codec(literal_profile(status="verified"), allow_experimental=False)
    bundle = FrameBundle.from_images([Image.new("RGB", (2, 1), "red")], [100])
    encoded = codec.encode_frame_bundle(bundle)
    assert encoded.packets[0].startswith(bytes.fromhex("F0 00 06 00"))
    assert encoded.packets[0].endswith(bytes.fromhex("0F"))


def test_capture_required_refuses_packet_claims() -> None:
    codec = select_codec(DeviceProfile(default_device_profile()), allow_experimental=True)
    with pytest.raises(CodecError):
        codec.encode_control("clear")


def test_chunk_payload_offsets() -> None:
    chunks = chunk_payload(b"abcdefghij", 4, delay_ms=2)
    assert [chunk.data for chunk in chunks] == [b"abcd", b"efgh", b"ij"]
    assert [chunk.offset for chunk in chunks] == [0, 4, 8]


def coolledx_profile(*, width: int = 64, height: int = 16) -> DeviceProfile:
    data = default_device_profile()
    data["dimensions"] = {"width": width, "height": height, "source": "test", "verified": True}
    data["write_characteristic"] = "0000fff1-0000-1000-8000-00805f9b34fb"
    data["notify_characteristic"] = "0000fff1-0000-1000-8000-00805f9b34fb"
    data["connection"] = {"mtu": 247, "maximum_chunk_size": 240, "inter_chunk_delay_ms": 0}
    data["protocol"] = {
        "codec": "coolledx",
        "status": "verified",
        "encryption": {"mode": "none"},
        "frame_transfer": {
            "status": "verified",
            "mode": "coolledx_bitplanes",
            "input_color_mode": "rgb888",
            "chunk_ack": {"requires_per_chunk_wait": True, "timeout_seconds": 0.1},
        },
    }
    return DeviceProfile(data)


def test_coolledx_control_framing_matches_hardware() -> None:
    codec = select_codec(coolledx_profile(), allow_experimental=False)
    # Exact framed bytes confirmed against panel ff:00:00:06:6f:82.
    assert codec.encode_control("brightness", 50).packets[0].hex() == "01000206088003"
    assert codec.encode_control("power", True).packets[0].hex() == "0100020609020503"
    assert codec.encode_control("power", False).packets[0].hex() == "01000206090003"
    # Control commands do not request ack pacing.
    assert codec.encode_control("brightness", 50).flow_control == {}


def test_map_user_scroll_speed() -> None:
    from opensign.protocol.codecs.coolledx import map_user_scroll_speed

    assert map_user_scroll_speed(0) == 0
    assert map_user_scroll_speed(10) == 255
    assert map_user_scroll_speed(5) == 128
    assert map_user_scroll_speed(8) == 204  # round(8 * 255 / 10)
    with pytest.raises(CodecError):
        map_user_scroll_speed(11)


def test_coolledx_encode_text_banner_uses_text_opcode() -> None:
    from opensign.animation.render import render_wide_text

    codec = select_codec(coolledx_profile(), allow_experimental=False)
    banner = render_wide_text("HELLO", 16)
    encoded = codec.encode_text_banner("HELLO", banner.tobytes(), banner.width)
    assert encoded.metadata["opcode"] == 0x02
    assert encoded.flow_control["await_ack"] is True
    assert encoded.metadata["banner_width"] == banner.width
    assert all(p[0] == 0x01 and p[-1] == 0x03 for p in encoded.packets)
    # Payload includes the 81-byte text header after 24 reserved bytes.
    assert encoded.metadata["payload_bytes"] > 24 + 81


def test_play_native_text_dry_run_maps_user_speed() -> None:
    from opensign.animation.render import render_wide_text
    from opensign.protocol.runtime import ProtocolRuntime

    profile = coolledx_profile()
    banner = render_wide_text("HI", 16)
    result = asyncio.run(
        ProtocolRuntime(profile).play_native_text(
            "HI",
            banner.tobytes(),
            banner.width,
            speed=8,
            execute=False,
        )
    )
    assert result["native_text"]["user_speed"] == 8
    assert result["native_text"]["device_speed"] == 204
    assert result["native_text"]["mode"] == 2
    assert [t["step"] for t in result["transfers"]] == ["banner", "speed", "mode"]
    assert result["transfers"][0]["transfer"]["dry_run"] is True
    assert result["encoded"]["banner"]["metadata"]["opcode"] == 0x02


def test_coolledx_frame_bundle_requests_ack_pacing() -> None:
    codec = select_codec(coolledx_profile(), allow_experimental=False)
    bundle = FrameBundle.from_images([Image.new("RGB", (64, 16), "white")], [100])
    encoded = codec.encode_frame_bundle(bundle)
    assert encoded.flow_control["await_ack"] is True
    assert encoded.flow_control["ack_timeout"] == 0.1
    # Every wire packet is a complete 0x01..0x03 frame.
    assert all(p[0] == 0x01 and p[-1] == 0x03 for p in encoded.packets)


def _animation_bundle(durations: list[int], *, size: tuple[int, int] = (64, 16)) -> FrameBundle:
    images = [Image.new("RGB", size, (i * 8 % 256, 0, 0)) for i in range(len(durations))]
    return FrameBundle.from_images(images, durations)


def test_coolledx_animation_speed_derived_from_frame_durations() -> None:
    codec = select_codec(coolledx_profile(), allow_experimental=False)
    encoded = codec.encode_frame_bundle(_animation_bundle([80, 80, 80]))
    assert encoded.metadata["opcode"] == 0x04
    assert encoded.metadata["frame_count"] == 3
    # Hardware-calibrated 2026-07-13: coolledx_speed is ms/frame, so 80ms => ~12.5fps.
    assert encoded.metadata["animation_speed"] == 80


def test_coolledx_animation_speed_uses_median_of_mixed_durations() -> None:
    codec = select_codec(coolledx_profile(), allow_experimental=False)
    encoded = codec.encode_frame_bundle(_animation_bundle([50, 100, 300]))
    assert encoded.metadata["animation_speed"] == 100


def test_coolledx_explicit_speed_override_wins_over_durations() -> None:
    codec = select_codec(coolledx_profile(), allow_experimental=False)
    bundle = _animation_bundle([80, 80])
    bundle.metadata["coolledx_speed"] = 1234
    assert codec.encode_frame_bundle(bundle).metadata["animation_speed"] == 1234


def test_coolledx_single_frame_uses_image_opcode_without_speed() -> None:
    codec = select_codec(coolledx_profile(), allow_experimental=False)
    encoded = codec.encode_frame_bundle(_animation_bundle([500]))
    assert encoded.metadata["opcode"] == 0x03
    assert encoded.metadata["animation_speed"] is None


def test_coolledx_rejects_over_budget_frame_count() -> None:
    # Use a tiny panel so 256 frames stay under the 30 KiB frame buffer and the
    # one-byte frame-count limit is what actually trips (256 * 8*8*3/8 = 6144 B).
    codec = select_codec(coolledx_profile(width=8, height=8), allow_experimental=False)
    over_budget = _animation_bundle([50] * 256, size=(8, 8))
    with pytest.raises(CodecError, match="one byte"):
        codec.encode_frame_bundle(over_budget)


def test_coolledx_accepts_animation_filling_the_frame_buffer() -> None:
    # 80 frames * (64*16*3/8) = 30720 B = exactly the 30 KiB device buffer (works on hardware).
    codec = select_codec(coolledx_profile(), allow_experimental=False)
    encoded = codec.encode_frame_bundle(_animation_bundle([80] * 80))
    assert encoded.metadata["opcode"] == 0x04
    assert encoded.metadata["frame_count"] == 80
    assert encoded.metadata["payload_bytes"] == 27 + 80 * 384


def test_coolledx_rejects_animation_over_frame_buffer() -> None:
    # 81 frames = 30.375 KiB: the device uploads it to 100% then displays nothing,
    # so the codec rejects it up front (measured 2026-07-13).
    codec = select_codec(coolledx_profile(), allow_experimental=False)
    with pytest.raises(CodecError, match="frame buffer"):
        codec.encode_frame_bundle(_animation_bundle([80] * 81))


def test_coolledx_gif_frame_timing_round_trips_to_wire_speed() -> None:
    # A GIF's own per-frame timing should survive rendering all the way to the speed field.
    frames = [Image.new("RGB", (64, 16), (0, 0, 0)) for _ in range(4)]
    for index, image in enumerate(frames):
        image.putpixel((index, 0), (255, 255, 255))
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=120, loop=0)
    buffer.seek(0)
    bundle = PixelAnimationStudio(64, 16).create_gif_bundle(buffer)
    encoded = select_codec(coolledx_profile(), allow_experimental=False).encode_frame_bundle(bundle)
    assert encoded.metadata["opcode"] == 0x04
    assert encoded.metadata["frame_count"] == 4
    assert encoded.metadata["animation_speed"] == 120


class _FakeBleakClient:
    """Minimal stand-in that records writes and optionally acks each one."""

    def __init__(self, transport: BleakTransport, *, ack: bool) -> None:
        self._transport = transport
        self._ack = ack
        self.is_connected = True
        self.mtu_size = 247
        self.writes: list[bytes] = []

    async def write_gatt_char(self, _char, data, *, response: bool = False) -> None:
        self.writes.append(bytes(data))
        if self._ack:
            # Simulate the device notifying an ack on FFF1.
            self._transport.notifications.append({"hex": bytes(data).hex(), "length": len(data)})
            self._transport._notify_event.set()


def _prime_transport(profile: DeviceProfile, *, ack: bool) -> BleakTransport:
    transport = BleakTransport(profile)
    transport.client = _FakeBleakClient(transport, ack=ack)
    transport.write_characteristic_object = object()
    transport.notify_subscribed = True
    return transport


def test_transport_waits_for_ack_per_packet() -> None:
    transport = _prime_transport(coolledx_profile(), ack=True)
    packets = [b"\x01\x00\x01aa\x03", b"\x01\x00\x01bb\x03", b"\x01\x00\x01cc\x03"]
    result = asyncio.run(transport.send_packets(packets, await_ack=True, ack_timeout=0.5))
    assert result.success is True
    assert result.awaited_ack is True
    assert result.acks_received == 3
    assert result.ack_timeouts == 0
    assert len(transport.client.writes) == 3


def test_transport_ack_timeout_is_soft() -> None:
    transport = _prime_transport(coolledx_profile(), ack=False)
    packets = [b"\x01\x00\x01aa\x03", b"\x01\x00\x01bb\x03"]
    result = asyncio.run(transport.send_packets(packets, await_ack=True, ack_timeout=0.05))
    # Writes still succeed; missing acks are a soft signal, not a failure.
    assert result.success is True
    assert result.acks_received == 0
    assert result.ack_timeouts == 2
    assert result.errors == []


def test_transport_control_does_not_wait_for_ack() -> None:
    transport = _prime_transport(coolledx_profile(), ack=False)
    result = asyncio.run(
        transport.send_packets([b"\x01\x00\x02\x08\x80\x03"], await_ack=False, ack_timeout=5.0)
    )
    assert result.success is True
    assert result.awaited_ack is False
    assert result.ack_timeouts == 0


def _ack_note(status: int, index: int = 0) -> dict:
    """A CoolLEDX-shaped ack notification: cmd 00 <index_be16> <status>."""
    data = bytes([0x03, 0x00]) + index.to_bytes(2, "big") + bytes([status])
    return {"hex": data.hex(), "length": len(data)}


class _StatusClient:
    """Fake client that acks each write with a scripted status byte.

    ``statuses`` is consumed one per write; the final value repeats once the list
    is exhausted, so ``[0x06]`` NAKs forever and ``[0x06, 0x00]`` NAKs once.
    """

    def __init__(self, transport: BleakTransport, statuses: list[int]) -> None:
        self._transport = transport
        self._statuses = list(statuses)
        self.is_connected = True
        self.mtu_size = 247
        self.writes: list[bytes] = []

    async def write_gatt_char(self, _char, data, *, response: bool = False) -> None:
        self.writes.append(bytes(data))
        status = self._statuses[min(len(self.writes) - 1, len(self._statuses) - 1)]
        self._transport.notifications.append(_ack_note(status))
        self._transport._notify_event.set()


def test_decode_coolledx_ack_status_bytes() -> None:
    from opensign.protocol.codecs.coolledx import decode_coolledx_ack

    assert decode_coolledx_ack(bytes.fromhex("0300000000"))["is_success"] is True
    nak = decode_coolledx_ack(bytes.fromhex("0300000006"))
    assert nak["is_nak"] is True and nak["is_success"] is False
    assert decode_coolledx_ack(b"")["status"] is None


def test_transport_resends_packet_on_nak_then_succeeds() -> None:
    from opensign.protocol.codecs.coolledx import decode_coolledx_ack

    transport = _prime_transport(coolledx_profile(), ack=False)
    transport.client = _StatusClient(transport, [0x06, 0x00])  # NAK once, then success
    result = asyncio.run(
        transport.send_packets(
            [b"\x01\x00\x01aa\x03"],
            await_ack=True,
            ack_timeout=0.5,
            ack_decoder=decode_coolledx_ack,
            nak_retry_limit=2,
        )
    )
    assert result.success is True
    assert result.nak_retries == 1
    assert result.acks_received == 1
    assert result.naks == 0
    assert len(transport.client.writes) == 2  # original + one re-send


def test_transport_nak_exhausts_retries_but_host_write_succeeds() -> None:
    from opensign.protocol.codecs.coolledx import decode_coolledx_ack

    transport = _prime_transport(coolledx_profile(), ack=False)
    transport.client = _StatusClient(transport, [0x06])  # always NAK
    result = asyncio.run(
        transport.send_packets(
            [b"\x01\x00\x01aa\x03"],
            await_ack=True,
            ack_timeout=0.5,
            ack_decoder=decode_coolledx_ack,
            nak_retry_limit=2,
        )
    )
    assert result.naks == 1
    assert result.nak_retries == 2
    assert result.acks_received == 0
    # Host wrote every byte; a NAK is a device signal, not a host-write failure.
    assert result.success is True
    assert len(transport.client.writes) == 3  # original + two re-sends


def test_transport_without_decoder_counts_bare_notification_as_ack() -> None:
    # Backward-compatible path: no codec decoder -> any notification is an ack.
    transport = _prime_transport(coolledx_profile(), ack=True)
    result = asyncio.run(
        transport.send_packets([b"\x01\x00\x01aa\x03"], await_ack=True, ack_timeout=0.5)
    )
    assert result.acks_received == 1
    assert result.naks == 0
    assert result.nak_retries == 0
