"""Bounded admission policy for request-scoped PCM playback.

Package C froze the visible rule: a producer cannot grow queued audio without
limit, and ``submit`` waits interruptibly until bounded native capacity admits
a slice. This module owns the SelectSpeak-side half of that rule — the
thresholds, the slice size, and the boundary arithmetic that keeps a sliced
submission equivalent to the whole. The waiting itself belongs to native
capacity accounting in Package J; nothing here polls or sleeps.

Thresholds are expressed in seconds and converted to frames against the
request format, because the contract states public capacities in frames while
the provisional values were chosen in seconds from Package A evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from .pcm import PcmBoundary, PcmFormat

# Provisional Package C values. These may be tuned from Package A evidence
# without reopening the contract; bounded interruptible admission may not.
LOW_WATER_SECONDS: Final = 1.0
HIGH_WATER_SECONDS: Final = 3.0
HARD_CAPACITY_SECONDS: Final = 4.0


@dataclass(frozen=True, slots=True)
class AdmissionPolicy:
    """Frame-denominated capacity thresholds for one request format."""

    low_water_frames: int
    high_water_frames: int
    hard_capacity_frames: int

    def __post_init__(self) -> None:
        if not 0 < self.low_water_frames <= self.high_water_frames:
            raise ValueError("low water must be positive and at most high water")
        if self.high_water_frames > self.hard_capacity_frames:
            raise ValueError("high water must not exceed hard capacity")

    @classmethod
    def for_format(
        cls,
        pcm_format: PcmFormat,
        *,
        low_water_seconds: float = LOW_WATER_SECONDS,
        high_water_seconds: float = HIGH_WATER_SECONDS,
        hard_capacity_seconds: float = HARD_CAPACITY_SECONDS,
    ) -> AdmissionPolicy:
        """Convert the provisional second-denominated thresholds to frames."""
        if not 0 < low_water_seconds <= high_water_seconds <= hard_capacity_seconds:
            raise ValueError("thresholds must be positive and nondecreasing")
        rate = pcm_format.sample_rate_hz
        return cls(
            max(1, round(low_water_seconds * rate)),
            max(1, round(high_water_seconds * rate)),
            max(1, round(hard_capacity_seconds * rate)),
        )

    @property
    def max_slice_frames(self) -> int:
        """The largest slice a single submission may offer.

        A slice must never exceed hard capacity, or a producer could deadlock
        waiting for room that the request can never provide. Bounding it at the
        high water mark additionally keeps one slice from consuming the whole
        queue, which preserves the hysteresis band native uses to schedule
        wakeups.
        """
        return self.high_water_frames

    def needs_more_audio(self, buffered_frames: int) -> bool:
        """Whether a producer should keep generating ahead of playback."""
        return buffered_frames < self.low_water_frames


@dataclass(frozen=True, slots=True)
class AdmissionSlice:
    """One bounded submission carrying its own slice-relative boundaries."""

    pcm: bytes
    boundaries: tuple[PcmBoundary, ...]
    frame_offset: int
    frame_count: int


def slice_for_admission(
    pcm: bytes | bytearray | memoryview,
    boundaries: Sequence[PcmBoundary],
    pcm_format: PcmFormat,
    policy: AdmissionPolicy,
) -> tuple[AdmissionSlice, ...]:
    """Cut PCM into slices that fit bounded admission, preserving boundaries.

    Boundary ``frame_offset`` values are slice-relative both before and after,
    so each boundary is rebased onto the slice that contains it. Text positions
    address the complete request and are never rewritten. Input order is
    preserved at equal offsets, which the contract requires.
    """
    payload = bytes(pcm)
    bytes_per_frame = pcm_format.bytes_per_frame
    if len(payload) % bytes_per_frame:
        raise ValueError("PCM byte length must contain complete frames")
    total_frames = len(payload) // bytes_per_frame

    ordered = tuple(boundaries)
    previous = 0
    for index, boundary in enumerate(ordered):
        if boundary.frame_offset > total_frames:
            raise ValueError("boundary frame_offset exceeds submitted PCM frames")
        if index and boundary.frame_offset < previous:
            raise ValueError("boundary frame_offset values must be nondecreasing")
        previous = boundary.frame_offset

    limit = policy.max_slice_frames
    if total_frames == 0:
        return (AdmissionSlice(payload, ordered, 0, 0),)

    slices: list[AdmissionSlice] = []
    next_boundary = 0
    for start in range(0, total_frames, limit):
        count = min(limit, total_frames - start)
        end = start + count
        # The final slice keeps any boundary sitting exactly at the end of the
        # PCM, which is a legal offset the contract permits.
        is_last = end >= total_frames
        carried: list[PcmBoundary] = []
        while next_boundary < len(ordered):
            boundary = ordered[next_boundary]
            if boundary.frame_offset > end or (boundary.frame_offset == end and not is_last):
                break
            carried.append(
                PcmBoundary(
                    boundary.frame_offset - start,
                    boundary.text_position,
                    boundary.text_length,
                )
            )
            next_boundary += 1
        slices.append(
            AdmissionSlice(
                payload[start * bytes_per_frame : end * bytes_per_frame],
                tuple(carried),
                start,
                count,
            )
        )
    return tuple(slices)
