from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _payload_bytes(packet: Mapping[str, Any]) -> bytes:
    value = packet.get("payload_hex", packet.get("hex", ""))
    if isinstance(value, bytes):
        return value
    if not isinstance(value, str):
        return b""
    cleaned = "".join(character for character in value if character in "0123456789abcdefABCDEF")
    if len(cleaned) % 2:
        return b""
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return b""


def normalize_trace(trace: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for sequence, packet in enumerate(trace):
        payload = _payload_bytes(packet)
        normalized.append(
            {
                "sequence": sequence,
                "direction": str(packet.get("direction", "unknown")),
                "characteristic": str(packet.get("characteristic", packet.get("uuid", "unknown"))),
                "timestamp": packet.get("timestamp"),
                "payload_hex": payload.hex(),
                "length": len(payload),
            }
        )
    return normalized


def _common_prefix_length(left: bytes, right: bytes) -> int:
    count = 0
    for first, second in zip(left, right, strict=False):
        if first != second:
            break
        count += 1
    return count


def _variable_positions(left: bytes, right: bytes) -> list[int]:
    maximum = max(len(left), len(right))
    return [
        index
        for index in range(maximum)
        if index >= len(left) or index >= len(right) or left[index] != right[index]
    ]


def diff_ble_sessions(
    baseline_capture: Iterable[Mapping[str, Any]],
    experiment_captures: Iterable[Iterable[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Compare normalized packet lists; PCAP decoding remains an explicit adapter boundary."""
    baseline = normalize_trace(baseline_capture)
    reports: list[dict[str, Any]] = []
    for capture_index, capture in enumerate(experiment_captures):
        candidate = normalize_trace(capture)
        aligned: list[dict[str, Any]] = []
        for packet_index in range(max(len(baseline), len(candidate))):
            base = baseline[packet_index] if packet_index < len(baseline) else None
            current = candidate[packet_index] if packet_index < len(candidate) else None
            if base is None or current is None:
                aligned.append(
                    {
                        "packet_index": packet_index,
                        "baseline": base,
                        "experiment": current,
                        "alignment": "missing_packet",
                    }
                )
                continue
            left = bytes.fromhex(base["payload_hex"])
            right = bytes.fromhex(current["payload_hex"])
            aligned.append(
                {
                    "packet_index": packet_index,
                    "direction_match": base["direction"] == current["direction"],
                    "characteristic_match": base["characteristic"] == current["characteristic"],
                    "baseline_length": len(left),
                    "experiment_length": len(right),
                    "common_prefix_length": _common_prefix_length(left, right),
                    "variable_positions": _variable_positions(left, right),
                    "baseline_payload_hex": left.hex(),
                    "experiment_payload_hex": right.hex(),
                }
            )
        reports.append(
            {
                "capture_index": capture_index,
                "packet_count": len(candidate),
                "alignment": aligned,
            }
        )
    return {
        "baseline_packet_count": len(baseline),
        "experiments": reports,
        "limitations": [
            "Alignment is sequence-based after normalization.",
            "Decode PCAP/HCI data into direction, characteristic, timestamp, and payload_hex first.",
            "Candidate length, checksum, hash, and session fields still require controlled experiments.",
        ],
    }


def rank_chipset_candidates(
    pcb_markings: Iterable[str],
    radio_observations: Mapping[str, Any],
    candidate_catalog: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score only caller-supplied catalog entries; never invent a chipset identity."""
    markings = {marking.casefold() for marking in pcb_markings if marking}
    candidates: list[dict[str, Any]] = []
    for entry in candidate_catalog or []:
        score = 0.0
        evidence: list[str] = []
        for pattern in entry.get("marking_patterns", []):
            pattern_folded = str(pattern).casefold()
            if any(pattern_folded in marking for marking in markings):
                score += 0.7
                evidence.append(f"marking_match:{pattern}")
        for key, expected in entry.get("radio_capabilities", {}).items():
            if radio_observations.get(key) == expected:
                score += 0.1
                evidence.append(f"radio_match:{key}={expected}")
        candidates.append(
            {
                "name": entry.get("name", "unnamed-candidate"),
                "confidence": min(round(score, 3), 0.95),
                "evidence": evidence,
                "confirmed": bool(score >= 0.7 and evidence and evidence[0].startswith("marking_match")),
            }
        )
    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    return {
        "candidates": candidates,
        "confirmed": [item for item in candidates if item["confirmed"]],
        "unknowns": [] if candidates else ["No candidate catalog or direct marking match was supplied."],
    }
