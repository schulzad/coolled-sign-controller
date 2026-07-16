from __future__ import annotations

import binascii
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from opensign.contracts import DeviceProfile, FrameBundle


class CodecError(RuntimeError):
    """Raised when a profile cannot safely encode the requested payload."""


class Codec(Protocol):
    name: str

    def encode_control(self, command: str, value: Any = None) -> "EncodedPayload": ...

    def encode_frame_bundle(self, frame_bundle: FrameBundle) -> "EncodedPayload": ...


@dataclass(slots=True)
class EncodedPayload:
    packets: list[bytes]
    payload_type: str
    codec: str
    expected_response: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Optional delivery pacing hints for the transport, e.g.
    # {"await_ack": True, "ack_timeout": 2.0, "scope": "per_packet"}.
    # Empty means "fire packets without waiting" (the default for control).
    flow_control: dict[str, Any] = field(default_factory=dict)
    # Optional codec-supplied ack decoder (bytes -> {index, status, is_success,
    # is_nak}). Kept off ``to_dict`` because it is a callable; the transport uses
    # it to tell a per-chunk success from a checksum-error NAK and re-send.
    ack_decoder: Callable[[bytes], dict[str, Any]] | None = None

    def to_dict(self, include_packet_hex: bool = True) -> dict[str, Any]:
        data = {
            "payload_type": self.payload_type,
            "codec": self.codec,
            "packet_count": len(self.packets),
            "total_bytes": sum(len(packet) for packet in self.packets),
            "expected_response": dict(self.expected_response),
            "flow_control": dict(self.flow_control),
            "metadata": dict(self.metadata),
        }
        if include_packet_hex:
            data["packets_hex"] = [packet.hex() for packet in self.packets]
        return data


def _parse_hex(value: str | bytes | bytearray, *, field_name: str = "hex value") -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if not isinstance(value, str):
        raise CodecError(f"{field_name} must be a hex string or bytes")
    cleaned = re.sub(r"0x", "", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\s:_,-]", "", cleaned)
    if not cleaned:
        return b""
    if len(cleaned) % 2:
        raise CodecError(f"{field_name} contains an odd number of hex digits")
    if re.search(r"[^0-9a-fA-F]", cleaned):
        raise CodecError(f"{field_name} contains non-hex characters")
    return bytes.fromhex(cleaned)


def _encode_integer(value: Any, encoding: str, *, field_name: str) -> bytes:
    if isinstance(value, bool):
        integer = int(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        integer = int(round(value))
    else:
        raise CodecError(f"{field_name} must be numeric for {encoding}")

    formats = {
        "u8": (1, "little", False),
        "i8": (1, "little", True),
        "u16le": (2, "little", False),
        "u16be": (2, "big", False),
        "i16le": (2, "little", True),
        "i16be": (2, "big", True),
        "u32le": (4, "little", False),
        "u32be": (4, "big", False),
    }
    if encoding not in formats:
        raise CodecError(f"Unsupported integer encoding: {encoding}")
    length, byteorder, signed = formats[encoding]
    try:
        return integer.to_bytes(length, byteorder=byteorder, signed=signed)
    except OverflowError as exc:
        raise CodecError(f"{field_name}={integer} does not fit {encoding}") from exc


def _resolve_placeholder(name: str, context: Mapping[str, Any]) -> bytes:
    if name == "value_bool":
        return bytes([1 if bool(context.get("value")) else 0])

    suffixes = ("u16le", "u16be", "i16le", "i16be", "u32le", "u32be", "u8", "i8")
    for suffix in suffixes:
        token = f"_{suffix}"
        if name.endswith(token):
            key = name[: -len(token)]
            if key not in context:
                raise CodecError(f"Template placeholder {{{name}}} has no context field {key!r}")
            return _encode_integer(context[key], suffix, field_name=key)

    if name.endswith("_hex"):
        key = name[:-4]
        if key not in context:
            raise CodecError(f"Template placeholder {{{name}}} has no context field {key!r}")
        return _parse_hex(context[key], field_name=key)

    raise CodecError(f"Unsupported template placeholder: {{{name}}}")


def render_hex_template(template: str, context: Mapping[str, Any]) -> bytes:
    """Render a restricted byte template without arbitrary expression evaluation."""
    if not isinstance(template, str) or not template.strip():
        raise CodecError("template_hex must be a non-empty string")
    output = bytearray()
    cursor = 0
    for match in re.finditer(r"\{([A-Za-z][A-Za-z0-9_]*)\}", template):
        output.extend(_parse_hex(template[cursor : match.start()], field_name="template literal"))
        output.extend(_resolve_placeholder(match.group(1), context))
        cursor = match.end()
    output.extend(_parse_hex(template[cursor:], field_name="template literal"))
    return bytes(output)


def _scale_value(value: Any, specification: Mapping[str, Any]) -> Any:
    scale = specification.get("value_scale")
    if not scale:
        return value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise CodecError("A numeric value is required when value_scale is configured")
    input_min = float(scale.get("input_min", 0))
    input_max = float(scale.get("input_max", 100))
    output_min = float(scale.get("output_min", 0))
    output_max = float(scale.get("output_max", 255))
    if input_max == input_min:
        raise CodecError("value_scale input range cannot be zero")
    numeric = float(value)
    if not input_min <= numeric <= input_max:
        if scale.get("clamp", False):
            numeric = min(max(numeric, input_min), input_max)
        else:
            raise CodecError(f"Value {value} is outside the configured range {input_min}..{input_max}")
    ratio = (numeric - input_min) / (input_max - input_min)
    return round(output_min + ratio * (output_max - output_min))


def apply_checksum(packet: bytes, specification: Mapping[str, Any] | None) -> bytes:
    if not specification:
        return packet
    algorithm = str(specification.get("algorithm", "none")).casefold()
    if algorithm == "none":
        return packet
    if algorithm == "sum8":
        checksum = (sum(packet) + int(specification.get("initial", 0))) & 0xFF
        return packet + bytes([checksum])
    if algorithm == "xor8":
        checksum = int(specification.get("initial", 0)) & 0xFF
        for byte in packet:
            checksum ^= byte
        return packet + bytes([checksum])
    if algorithm in {"crc16_ccitt", "crc16-ccitt"}:
        initial = int(specification.get("initial", 0xFFFF)) & 0xFFFF
        checksum = binascii.crc_hqx(packet, initial)
        byteorder = str(specification.get("byteorder", "big"))
        if byteorder not in {"little", "big"}:
            raise CodecError("CRC byteorder must be little or big")
        return packet + checksum.to_bytes(2, byteorder)
    raise CodecError(f"Unsupported checksum algorithm: {algorithm}")


class CaptureRequiredCodec:
    name = "capture_required"

    def _error(self, payload_type: str) -> CodecError:
        return CodecError(
            f"No verified {payload_type} codec is configured for this device profile. "
            "Capture and isolate the original application's traffic, then promote evidence into an experimental profile."
        )

    def encode_control(self, command: str, value: Any = None) -> EncodedPayload:
        raise self._error(f"control command {command!r}")

    def encode_frame_bundle(self, frame_bundle: FrameBundle) -> EncodedPayload:
        raise self._error("frame-transfer")


class ProfileLiteralCodec:
    """Restricted evidence codec for literal bytes and profile-defined templates."""

    name = "profile_literal"

    def __init__(self, profile: DeviceProfile, *, allow_experimental: bool = False):
        self.profile = profile
        self.protocol = profile.protocol
        self.allow_experimental = allow_experimental
        protocol_status = self.protocol.get("status", "unverified")
        allowed = {"verified", "experimental"} if allow_experimental else {"verified"}
        if protocol_status not in allowed:
            mode = "dry-run" if allow_experimental else "physical execution"
            raise CodecError(
                f"profile_literal protocol status {protocol_status!r} is not allowed for {mode}"
            )
        if protocol_status == "rejected":
            raise CodecError("Rejected protocol profiles cannot be selected")

    def _validate_spec(self, specification: Mapping[str, Any], *, label: str) -> None:
        status = specification.get("status", "unverified")
        allowed = {"verified", "experimental"} if self.allow_experimental else {"verified"}
        if status not in allowed:
            raise CodecError(f"{label} status {status!r} is not allowed")
        if not self.allow_experimental and not specification.get("replay_safe", False):
            raise CodecError(f"{label} must be explicitly marked replay_safe for physical execution")

        encryption_mode = str(self.protocol.get("encryption", {}).get("mode", "unknown")).casefold()
        if encryption_mode != "none" and not specification.get("pretransformed", False):
            raise CodecError(
                f"{label} cannot be encoded while encryption/session transform mode is {encryption_mode!r}; "
                "provide a codec plugin or mark captured final bytes as pretransformed"
            )

    def encode_control(self, command: str, value: Any = None) -> EncodedPayload:
        commands = self.protocol.get("commands", {})
        specification = commands.get(command)
        if not isinstance(specification, Mapping):
            raise CodecError(f"Control command {command!r} is not configured in the profile")
        self._validate_spec(specification, label=f"command {command!r}")
        transformed = _scale_value(value, specification)
        if specification.get("payload_hex") is not None:
            packet = _parse_hex(specification.get("payload_hex", ""), field_name=f"{command}.payload_hex")
        elif specification.get("template_hex"):
            packet = render_hex_template(
                str(specification["template_hex"]),
                {
                    "value": transformed,
                    "payload": specification.get("payload_hex", ""),
                },
            )
        else:
            raise CodecError(f"Command {command!r} needs payload_hex or template_hex")
        packet = apply_checksum(packet, specification.get("checksum"))
        if not packet and not specification.get("allow_empty", False):
            raise CodecError(f"Command {command!r} encoded to an empty packet")
        return EncodedPayload(
            packets=[packet],
            payload_type="control",
            codec=self.name,
            expected_response=dict(specification.get("expected_response", {})),
            metadata={
                "command": command,
                "status": specification.get("status"),
                "evidence": list(specification.get("evidence", [])),
                "value_input": value,
                "value_encoded": transformed,
            },
        )

    def encode_frame_bundle(self, frame_bundle: FrameBundle) -> EncodedPayload:
        specification = self.protocol.get("frame_transfer", {})
        if not isinstance(specification, Mapping):
            raise CodecError("protocol.frame_transfer must be an object")
        self._validate_spec(specification, label="frame transfer")
        expected_color_mode = specification.get("input_color_mode")
        if expected_color_mode and expected_color_mode != frame_bundle.color_mode:
            raise CodecError(
                f"Frame transfer expects {expected_color_mode}, but bundle is {frame_bundle.color_mode}"
            )

        mode = specification.get("mode")
        packets: list[bytes] = []
        if mode == "preencoded_packets":
            packet_hex = frame_bundle.metadata.get("transport_packets_hex")
            if not isinstance(packet_hex, list) or not packet_hex:
                raise CodecError(
                    "preencoded_packets mode requires frame_bundle.metadata.transport_packets_hex"
                )
            packets = [
                _parse_hex(item, field_name=f"transport_packets_hex[{index}]")
                for index, item in enumerate(packet_hex)
            ]
        elif mode == "per_frame_template":
            template = specification.get("packet_template_hex")
            if not template:
                raise CodecError("per_frame_template mode requires packet_template_hex")
            frame_count = len(frame_bundle.frames)
            for index, frame in enumerate(frame_bundle.frames):
                context = {
                    "frame": frame,
                    "payload": frame,
                    "width": frame_bundle.width,
                    "height": frame_bundle.height,
                    "frame_index": index,
                    "frame_count": frame_count,
                    "frame_length": len(frame),
                    "frame_hash8": bytes.fromhex(frame_bundle.frame_hashes[index][:16]),
                    "prefix": specification.get("prefix_hex", ""),
                    "suffix": specification.get("suffix_hex", ""),
                }
                packet = render_hex_template(str(template), context)
                packets.append(apply_checksum(packet, specification.get("checksum")))
        elif mode == "whole_bundle_template":
            template = specification.get("packet_template_hex")
            if not template:
                raise CodecError("whole_bundle_template mode requires packet_template_hex")
            payload = b"".join(frame_bundle.frames)
            context = {
                "payload": payload,
                "width": frame_bundle.width,
                "height": frame_bundle.height,
                "frame_count": len(frame_bundle.frames),
                "frame_length": len(payload),
                "prefix": specification.get("prefix_hex", ""),
                "suffix": specification.get("suffix_hex", ""),
            }
            packets = [
                apply_checksum(
                    render_hex_template(str(template), context),
                    specification.get("checksum"),
                )
            ]
        else:
            raise CodecError(
                "frame_transfer.mode must be preencoded_packets, per_frame_template, or whole_bundle_template"
            )

        if not packets or any(not packet for packet in packets):
            raise CodecError("Frame transfer produced an empty packet")
        return EncodedPayload(
            packets=packets,
            payload_type="frame_bundle",
            codec=self.name,
            expected_response=dict(specification.get("expected_response", {})),
            metadata={
                "status": specification.get("status"),
                "mode": mode,
                "evidence": list(specification.get("evidence", [])),
                "frame_bundle": frame_bundle.summary(),
            },
        )


CodecFactory = Callable[[DeviceProfile, bool], Codec]
_CODEC_FACTORIES: dict[str, CodecFactory] = {
    "capture_required": lambda profile, allow_experimental: CaptureRequiredCodec(),
    "profile_literal": lambda profile, allow_experimental: ProfileLiteralCodec(
        profile, allow_experimental=allow_experimental
    ),
}


def register_codec(name: str, factory: CodecFactory) -> None:
    if not name or not callable(factory):
        raise ValueError("Codec name and callable factory are required")
    _CODEC_FACTORIES[name] = factory


def select_codec(profile: DeviceProfile, *, allow_experimental: bool = False) -> Codec:
    codec_name = str(profile.protocol.get("codec", "capture_required"))
    factory = _CODEC_FACTORIES.get(codec_name)
    if factory is None:
        raise CodecError(
            f"Codec {codec_name!r} is not registered. Install or register an explicit device codec plugin."
        )
    return factory(profile, allow_experimental)
