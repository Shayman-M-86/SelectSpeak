import threading

import pytest

from selectspeak.speech.admission import (
    HARD_CAPACITY_SECONDS,
    HIGH_WATER_SECONDS,
    LOW_WATER_SECONDS,
    AdmissionPolicy,
    slice_for_admission,
)
from selectspeak.speech.pcm import PcmBoundary, PcmFormat

FORMAT = PcmFormat(1000)


def _policy(low: int = 10, high: int = 100, hard: int = 200) -> AdmissionPolicy:
    return AdmissionPolicy(low_water_frames=low, high_water_frames=high, hard_capacity_frames=hard)


def _pcm(frames: int) -> bytes:
    return b"\x01\x02" * frames


def test_provisional_thresholds_match_the_frozen_contract() -> None:
    assert (LOW_WATER_SECONDS, HIGH_WATER_SECONDS, HARD_CAPACITY_SECONDS) == (1.0, 3.0, 4.0)


def test_policy_converts_seconds_to_frames_against_the_request_format() -> None:
    policy = AdmissionPolicy.for_format(PcmFormat(44_100))

    assert policy.low_water_frames == 44_100
    assert policy.high_water_frames == 132_300
    assert policy.hard_capacity_frames == 176_400


def test_a_slice_never_exceeds_hard_capacity() -> None:
    policy = AdmissionPolicy.for_format(FORMAT)

    assert policy.max_slice_frames <= policy.hard_capacity_frames


@pytest.mark.parametrize(
    "low,high,hard",
    [(0, 10, 20), (20, 10, 30), (10, 40, 30)],
)
def test_policy_rejects_thresholds_that_cannot_bound_admission(low: int, high: int, hard: int) -> None:
    with pytest.raises(ValueError):
        AdmissionPolicy(low_water_frames=low, high_water_frames=high, hard_capacity_frames=hard)


def test_producer_generates_ahead_only_below_low_water() -> None:
    policy = _policy()

    assert policy.needs_more_audio(0)
    assert policy.needs_more_audio(9)
    assert not policy.needs_more_audio(10)
    assert not policy.needs_more_audio(500)


def test_pcm_within_one_slice_is_not_cut() -> None:
    slices = slice_for_admission(_pcm(50), [], FORMAT, _policy())

    assert len(slices) == 1
    assert slices[0].frame_count == 50


def test_slicing_preserves_every_frame_exactly_once() -> None:
    payload = _pcm(250)

    slices = slice_for_admission(payload, [], FORMAT, _policy())

    assert b"".join(s.pcm for s in slices) == payload
    assert sum(s.frame_count for s in slices) == 250


def test_boundaries_are_rebased_onto_the_slice_that_contains_them() -> None:
    boundaries = [PcmBoundary(0, 0, 1), PcmBoundary(100, 1, 1), PcmBoundary(150, 2, 1)]

    slices = slice_for_admission(_pcm(250), boundaries, FORMAT, _policy())

    assert [b.frame_offset for b in slices[0].boundaries] == [0]
    # Frame 100 opens the second slice rather than closing the first.
    assert [b.frame_offset for b in slices[1].boundaries] == [0, 50]
    assert [b.text_position for b in slices[1].boundaries] == [1, 2]


def test_a_boundary_at_the_end_of_the_pcm_stays_in_the_final_slice() -> None:
    slices = slice_for_admission(_pcm(250), [PcmBoundary(250, 3, 1)], FORMAT, _policy())

    assert slices[-1].boundaries == (PcmBoundary(50, 3, 1),)
    assert sum(len(s.boundaries) for s in slices) == 1


def test_every_boundary_survives_slicing_exactly_once() -> None:
    boundaries = [PcmBoundary(offset, offset, 1) for offset in range(0, 250, 7)]

    slices = slice_for_admission(_pcm(250), boundaries, FORMAT, _policy())

    recovered = [
        (b.frame_offset + s.frame_offset, b.text_position, b.text_length)
        for s in slices
        for b in s.boundaries
    ]
    assert recovered == [(b.frame_offset, b.text_position, b.text_length) for b in boundaries]


def test_text_positions_are_never_rewritten_by_slicing() -> None:
    boundaries = [PcmBoundary(120, 40, 5)]

    slices = slice_for_admission(_pcm(250), boundaries, FORMAT, _policy())

    carried = [b for s in slices for b in s.boundaries]
    assert carried[0].text_position == 40
    assert carried[0].text_length == 5


def test_empty_pcm_still_yields_one_submission() -> None:
    slices = slice_for_admission(b"", [], FORMAT, _policy())

    assert len(slices) == 1
    assert slices[0].frame_count == 0


def test_slicing_rejects_incomplete_frames() -> None:
    with pytest.raises(ValueError, match="complete frames"):
        slice_for_admission(b"\x01", [], FORMAT, _policy())


def test_slicing_rejects_a_boundary_past_the_pcm() -> None:
    with pytest.raises(ValueError, match="exceeds submitted PCM frames"):
        slice_for_admission(_pcm(10), [PcmBoundary(11, 0, 1)], FORMAT, _policy())


def test_slicing_rejects_out_of_order_boundaries() -> None:
    boundaries = [PcmBoundary(5, 0, 1), PcmBoundary(2, 1, 1)]

    with pytest.raises(ValueError, match="nondecreasing"):
        slice_for_admission(_pcm(10), boundaries, FORMAT, _policy())


def test_equal_offset_boundaries_keep_their_input_order() -> None:
    boundaries = [PcmBoundary(30, 9, 1), PcmBoundary(30, 4, 1)]

    slices = slice_for_admission(_pcm(50), boundaries, FORMAT, _policy())

    assert [b.text_position for b in slices[0].boundaries] == [9, 4]


def test_slicing_is_deterministic_across_threads() -> None:
    payload = _pcm(250)
    boundaries = [PcmBoundary(offset, offset, 1) for offset in range(0, 250, 11)]
    results: list[tuple[int, ...]] = []
    lock = threading.Lock()

    def run() -> None:
        sliced = slice_for_admission(payload, boundaries, FORMAT, _policy())
        with lock:
            results.append(tuple(s.frame_count for s in sliced))

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(results)) == 1
