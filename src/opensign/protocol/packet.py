from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True, frozen=True)
class Chunk:
    packet_index: int
    chunk_index: int
    offset: int
    data: bytes
    delay_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "packet_index": self.packet_index,
            "chunk_index": self.chunk_index,
            "offset": self.offset,
            "length": len(self.data),
            "hex": self.data.hex(),
            "delay_ms": self.delay_ms,
        }


def chunk_payload(
    payload: bytes,
    maximum_chunk_size: int,
    *,
    packet_index: int = 0,
    delay_ms: float = 0.0,
) -> list[Chunk]:
    if maximum_chunk_size <= 0:
        raise ValueError("maximum_chunk_size must be positive")
    if delay_ms < 0:
        raise ValueError("delay_ms cannot be negative")
    return [
        Chunk(
            packet_index=packet_index,
            chunk_index=chunk_index,
            offset=offset,
            data=payload[offset : offset + maximum_chunk_size],
            delay_ms=delay_ms,
        )
        for chunk_index, offset in enumerate(range(0, len(payload), maximum_chunk_size))
    ]


def chunk_packets(
    packets: Iterable[bytes],
    maximum_chunk_size: int,
    *,
    delay_ms: float = 0.0,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for packet_index, packet in enumerate(packets):
        chunks.extend(
            chunk_payload(
                bytes(packet),
                maximum_chunk_size,
                packet_index=packet_index,
                delay_ms=delay_ms,
            )
        )
    return chunks
