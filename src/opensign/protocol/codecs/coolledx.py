"""CoolLEDX device codec.

Implements the framing and command set for signs that advertise as ``CoolLEDX``
and expose the ``FFF0``/``FFF1`` vendor service (controlled by the CoolLED1248
app). This is a device codec plugin: it encodes bytes for a specific, externally
documented protocol rather than discovering protocol semantics.

Protocol summary (byte stream written to the FFF1 characteristic):

    frame  = 0x01  ||  escape( len_be16 || payload )  ||  0x03
    payload= command_byte || command_args
    escape : 0x02 -> 0x02 0x06 ; 0x01 -> 0x02 0x05 ; 0x03 -> 0x02 0x07

Control commands are a single opcode plus (optionally) one argument byte. Image
and animation transfers pack the frame into three column-major 1-bit planes
(R, G, B; MSB = top pixel), prepend a small header, split the result into
128-byte data chunks with per-chunk headers and an XOR checksum, and frame each
chunk individually.

Provenance: the framing, opcodes, and pixel packing are derived from the
public reverse-engineering in the ``coolledx`` driver
(https://github.com/UpDryTwist/coolledx-driver, itself derived from
CrimsonClyde's led-faceshields work). Treat entries as ``experimental`` until
confirmed against the specific physical panel.
"""

from __future__ import annotations

from typing import Any, Mapping

from opensign.contracts import DeviceProfile, FrameBundle

from ..codec import CodecError, EncodedPayload, register_codec

# Framing bytes.
FRAME_START = 0x01
FRAME_END = 0x03
ESCAPE_PREFIX = 0x02
ESCAPE_OFFSET = 0x04

# Single-byte command opcodes (CoolLEDX generation).
OPCODE_MUSIC = 0x01
OPCODE_TEXT = 0x02
OPCODE_IMAGE = 0x03
OPCODE_ANIMATION = 0x04
OPCODE_MODE = 0x06
OPCODE_SPEED = 0x07
OPCODE_BRIGHTNESS = 0x08
OPCODE_SWITCH = 0x09
OPCODE_INVERT_DISPLAY = 0x0C
OPCODE_POWER_DOWN = 0x12
OPCODE_POWER_ON = 0x13

PIXELS_PER_BYTE = 8
CHUNK_DATA_SIZE = 128
DEFAULT_ANIMATION_SPEED = 512

# Hard protocol ceilings (see framing above): the animation header stores the
# frame count in a single byte and each chunk header stores the full payload
# length in two bytes. Exceeding either yields a friendly error instead of a raw
# OverflowError from ``int.to_bytes``.
FRAME_COUNT_MAX = 0xFF
PAYLOAD_BYTES_MAX = 0xFFFF


def escape_stream(data: bytes) -> bytes:
    """Byte-stuff 0x01/0x02/0x03 so they cannot be confused with framing bytes."""
    out = bytearray()
    for byte in data:
        if byte < ESCAPE_OFFSET:  # 0x00..0x03
            if byte == 0x00:
                out.append(0x00)
            else:
                out.append(ESCAPE_PREFIX)
                out.append(byte + ESCAPE_OFFSET)
        else:
            out.append(byte)
    return bytes(out)


def frame_payload(payload: bytes) -> bytes:
    """Wrap a raw payload (command + args) in the CoolLEDX framing."""
    extended = len(payload).to_bytes(2, "big") + payload
    return bytes([FRAME_START]) + escape_stream(extended) + bytes([FRAME_END])


def _xor_checksum(data: bytes) -> int:
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum & 0xFF


def _pixel_bitplanes(frame: bytes, width: int, height: int) -> tuple[bytearray, bytearray, bytearray]:
    """Convert an RGB888 (row-major) frame into column-major 1-bit R/G/B planes.

    Columns are packed top-to-bottom; the most significant bit of each byte is
    the topmost pixel. ``height`` must be a multiple of 8.
    """
    if height % PIXELS_PER_BYTE != 0:
        raise CodecError("CoolLEDX frame height must be a multiple of 8")
    expected = width * height * 3
    if len(frame) != expected:
        raise CodecError(f"Frame has {len(frame)} bytes; expected {expected} for {width}x{height} RGB888")

    plane_r, plane_g, plane_b = bytearray(), bytearray(), bytearray()
    tmp_r = tmp_g = tmp_b = 0
    for x in range(width):
        for y in range(height):
            offset = (y * width + x) * 3
            tmp_r = (tmp_r << 1) | (1 if frame[offset] > 127 else 0)
            tmp_g = (tmp_g << 1) | (1 if frame[offset + 1] > 127 else 0)
            tmp_b = (tmp_b << 1) | (1 if frame[offset + 2] > 127 else 0)
            if y % PIXELS_PER_BYTE == PIXELS_PER_BYTE - 1:
                plane_r.append(tmp_r)
                plane_g.append(tmp_g)
                plane_b.append(tmp_b)
                tmp_r = tmp_g = tmp_b = 0
    return plane_r, plane_g, plane_b


def _chop_into_chunks(data: bytes, command: int) -> list[bytes]:
    """Split ``data`` into framed 128-byte chunks with headers and checksums."""
    chunks: list[bytes] = []
    total = len(data)
    for chunk_id, start in enumerate(range(0, max(total, 1), CHUNK_DATA_SIZE)):
        raw_chunk = data[start : start + CHUNK_DATA_SIZE]
        formatted = bytearray()
        formatted += b"\x00"  # reserved byte (purpose unconfirmed)
        formatted += total.to_bytes(2, "big")  # full payload length before splitting
        formatted += chunk_id.to_bytes(2, "big")  # chunk index
        formatted += len(raw_chunk).to_bytes(1, "big")  # this chunk's size
        formatted += raw_chunk
        formatted.append(_xor_checksum(bytes(formatted)))
        payload = bytes([command]) + bytes(formatted)
        chunks.append(frame_payload(payload))
    return chunks


class CoolLEDXCodec:
    """Encoder for CoolLEDX-family signs (service FFF0 / characteristic FFF1)."""

    name = "coolledx"

    def __init__(self, profile: DeviceProfile, *, allow_experimental: bool = False):
        self.profile = profile
        self.protocol = profile.protocol
        self.width, self.height = profile.dimensions
        status = str(self.protocol.get("status", "unverified"))
        # This codec encodes an externally documented protocol; a controlled
        # live test is exactly how we move it from experimental to verified, so
        # both dry-run and physical execution are permitted once a profile has
        # opted in at experimental or verified status.
        if status not in {"experimental", "verified"}:
            raise CodecError(
                f"CoolLEDX codec requires protocol.status 'experimental' or 'verified', not {status!r}"
            )

    # -- control -----------------------------------------------------------

    def encode_control(self, command: str, value: Any = None) -> EncodedPayload:
        name = command.strip().casefold()
        encoded_value: Any = value

        if name == "brightness":
            encoded_value = self._brightness_byte(value)
            payload = bytes([OPCODE_BRIGHTNESS, encoded_value])
        elif name in {"power", "switch", "on_off"}:
            on = bool(value)
            encoded_value = on
            payload = bytes([OPCODE_SWITCH, 1 if on else 0])
        elif name == "power_on":
            payload = bytes([OPCODE_POWER_ON])
        elif name == "power_down":
            payload = bytes([OPCODE_POWER_DOWN])
        elif name == "speed":
            encoded_value = self._byte(value, "speed")
            payload = bytes([OPCODE_SPEED, encoded_value])
        elif name == "mode":
            encoded_value = self._byte(value, "mode")
            payload = bytes([OPCODE_MODE, encoded_value])
        elif name in {"invert", "invert_display"}:
            on = bool(value)
            encoded_value = on
            payload = bytes([OPCODE_INVERT_DISPLAY, 1 if on else 0])
        else:
            raise CodecError(f"CoolLEDX codec has no control command named {command!r}")

        packet = frame_payload(payload)
        return EncodedPayload(
            packets=[packet],
            payload_type="control",
            codec=self.name,
            expected_response={"channel": "notify", "characteristic": self.profile.notify_characteristic},
            metadata={
                "command": name,
                "status": self.protocol.get("status"),
                "value_input": value,
                "value_encoded": encoded_value,
                "payload_hex": payload.hex(),
            },
        )

    @staticmethod
    def _brightness_byte(value: Any) -> int:
        if value is None:
            return 0xFF
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CodecError("brightness requires a numeric value")
        numeric = float(value)
        if numeric <= 100:  # treat as a 0-100 percentage
            numeric = max(0.0, numeric) / 100.0 * 255.0
        return max(0, min(255, round(numeric)))

    @staticmethod
    def _byte(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CodecError(f"{field} requires a numeric value")
        return max(0, min(255, int(round(value))))

    # -- frame transfer ----------------------------------------------------

    def encode_frame_bundle(self, frame_bundle: FrameBundle) -> EncodedPayload:
        if frame_bundle.width != self.width or frame_bundle.height != self.height:
            raise CodecError(
                f"Frame bundle is {frame_bundle.width}x{frame_bundle.height}; "
                f"panel is {self.width}x{self.height}"
            )

        frames = frame_bundle.frames
        frame_count = len(frames)
        if frame_count > FRAME_COUNT_MAX:
            per_frame = max(1, self.width * self.height * 3 // PIXELS_PER_BYTE)
            raise CodecError(
                f"Animation has {frame_count} frames, but CoolLEDX stores the frame "
                f"count in one byte, so at most {FRAME_COUNT_MAX} frames fit. At "
                f"{self.width}x{self.height} the payload budget also caps you near "
                f"{PAYLOAD_BYTES_MAX // per_frame} frames. Lower max_frames or raise fps."
            )

        animation_speed: int | None = None
        if len(frames) == 1:
            command = OPCODE_IMAGE
            plane_r, plane_g, plane_b = _pixel_bitplanes(frames[0], self.width, self.height)
            pixel_bits = bytes(plane_r + plane_g + plane_b)
            raw = bytearray(24)  # reserved header (purpose unconfirmed)
            raw += len(pixel_bits).to_bytes(2, "big")
            raw += pixel_bits
        else:
            command = OPCODE_ANIMATION
            all_r, all_g, all_b = bytearray(), bytearray(), bytearray()
            for frame in frames:
                plane_r, plane_g, plane_b = _pixel_bitplanes(frame, self.width, self.height)
                all_r += plane_r
                all_g += plane_g
                all_b += plane_b
            pixel_bits = bytes(all_r + all_g + all_b)
            animation_speed = self._animation_speed(frame_bundle)
            raw = bytearray(24)
            raw += len(frames).to_bytes(1, "big")
            raw += animation_speed.to_bytes(2, "big")
            raw += pixel_bits

        if len(raw) > PAYLOAD_BYTES_MAX:
            per_frame = max(1, self.width * self.height * 3 // PIXELS_PER_BYTE)
            raise CodecError(
                f"Encoded payload is {len(raw)} bytes, over the {PAYLOAD_BYTES_MAX}-byte "
                f"CoolLEDX chunk-length limit (~{PAYLOAD_BYTES_MAX // per_frame} frames at "
                f"{self.width}x{self.height}). Reduce the frame count or panel size."
            )

        packets = _chop_into_chunks(bytes(raw), command)
        return EncodedPayload(
            packets=packets,
            payload_type="frame_bundle",
            codec=self.name,
            expected_response={"channel": "notify", "characteristic": self.profile.notify_characteristic},
            flow_control={
                "await_ack": True,
                "ack_timeout": self._ack_timeout(),
                "scope": "per_packet",
            },
            metadata={
                "status": self.protocol.get("status"),
                "opcode": command,
                "frame_count": len(frames),
                "animation_speed": animation_speed,
                "payload_bytes": len(raw),
                "frame_bundle": frame_bundle.summary(),
            },
        )

    def _ack_timeout(self) -> float:
        """Per-chunk ack wait; the device notifies FFF1 after each frame chunk."""
        transfer = self.protocol.get("frame_transfer", {})
        if isinstance(transfer, Mapping):
            ack = transfer.get("chunk_ack")
            if isinstance(ack, Mapping) and isinstance(ack.get("timeout_seconds"), (int, float)):
                return float(ack["timeout_seconds"])
        return 2.0

    def _animation_speed(self, frame_bundle: FrameBundle) -> int:
        """Per-frame hold time in milliseconds.

        Calibrated on hardware 2026-07-13: the CoolLEDX animation speed field is
        the ms-per-frame hold time (smaller = faster), so speed == round(1000 / fps).
        Priority: explicit ``coolledx_speed`` override, then the bundle's own
        per-frame timing (median), then the profile default, then the constant.
        """
        override = frame_bundle.metadata.get("coolledx_speed")
        if isinstance(override, (int, float)) and not isinstance(override, bool):
            return max(1, min(0xFFFF, int(round(override))))
        durations = [int(d) for d in frame_bundle.frame_durations_ms if d and d > 0]
        if durations:
            durations.sort()
            representative = durations[len(durations) // 2]  # median hold time (ms)
            return max(1, min(0xFFFF, representative))
        transfer = self.protocol.get("frame_transfer", {})
        if isinstance(transfer, Mapping) and isinstance(transfer.get("speed"), (int, float)):
            return max(1, min(0xFFFF, int(transfer["speed"])))
        return DEFAULT_ANIMATION_SPEED


def _factory(profile: DeviceProfile, allow_experimental: bool) -> CoolLEDXCodec:
    return CoolLEDXCodec(profile, allow_experimental=allow_experimental)


register_codec("coolledx", _factory)
