from typing import Any

import numpy as np
import pytest

from selectspeak.config import AppConfig
from selectspeak.speech.backends.supertonic import (
    SupertonicSpeaker,
    _PreparedSegment,
    estimate_word_boundaries,
    normalize_edge_silence,
)
from selectspeak.speech.pipeline import (
    MIN_CHUNK_CHARACTERS,
    GenerationStatistics,
)
from selectspeak.speech.playback import PlaybackController
from selectspeak.speech.segments import SpeechSegment


def test_estimated_boundaries_follow_text_positions_and_audio_duration() -> None:
    boundaries = estimate_word_boundaries("The quick brown fox.", 2.0)

    assert [(item.position, item.length) for item in boundaries] == [
        (0, 3),
        (4, 5),
        (10, 5),
        (16, 3),
    ]
    assert boundaries[0].seconds == 0
    assert 0 < boundaries[-1].seconds < 2.0


def test_longer_words_receive_more_timeline_weight() -> None:
    boundaries = estimate_word_boundaries("cat interesting dog", 3.0)

    first_gap = boundaries[1].seconds - boundaries[0].seconds
    second_gap = boundaries[2].seconds - boundaries[1].seconds
    assert second_gap > first_gap


def test_punctuation_adds_a_pause_before_the_next_word() -> None:
    plain = estimate_word_boundaries("one two three", 3.0)
    punctuated = estimate_word_boundaries("one, two three", 3.0)

    assert punctuated[1].seconds > plain[1].seconds


@pytest.mark.parametrize("text,duration", [("", 1.0), ("...", 1.0), ("word", 0)])
def test_estimated_boundaries_handle_empty_inputs(text: str, duration: float) -> None:
    assert estimate_word_boundaries(text, duration) == []


def test_edge_silence_is_trimmed_with_small_safety_padding() -> None:
    sample_rate = 1000
    audio = np.concatenate(
        (np.zeros(400), np.full(500, 0.5), np.zeros(600))
    ).astype(np.float32)

    normalized, leading, spoken = normalize_edge_silence(audio, sample_rate)

    assert leading == pytest.approx(0.015)
    assert spoken == pytest.approx(0.5)
    assert normalized.size / sample_rate == pytest.approx(0.53)


class _FakePlayer:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self._fed_bytes = 0

    @property
    def fed_bytes(self) -> int:
        return self._fed_bytes

    @property
    def buffered_seconds(self) -> float:
        return 0.0

    def start(self) -> None:
        self.events.append(("start", None))

    def feed(self, data: bytes) -> None:
        self.events.append(("feed", data))
        self._fed_bytes += len(data)

    def feed_silence(self, seconds: float) -> None:
        self.events.append(("silence", seconds))
        self._fed_bytes += round(seconds * 2000)

    def add_boundary(
        self,
        offset_ticks: int,
        position: int,
        length: int,
        *,
        base_byte_offset: int = 0,
    ) -> None:
        self.events.append(
            (
                "boundary",
                (offset_ticks, position, length, base_byte_offset),
            )
        )

    def finish(self) -> None:
        self.events.append(("finish", None))


def test_supertonic_uses_one_stream_and_only_pauses_at_sentence_boundaries() -> None:
    text = (
        "The ultrasound does not prove sarcoidosis, because other inflammatory "
        "conditions can cause soft-tissue inflammation. But the next sentence "
        "also needs enough words to be divided at a technical chunk boundary."
    )
    speaker = object.__new__(SupertonicSpeaker)
    speaker._config = AppConfig(structure_pause_seconds=0.1).speech
    speaker._playback = PlaybackController()
    request, _active = speaker._playback.submit(text)
    speaker._word_callback = None
    speaker._request_text = ""
    speaker._generation_statistics = GenerationStatistics()
    player = _FakePlayer()
    speaker._player = player
    synthesis_events: list[str] = []

    def synthesize(segment: SpeechSegment) -> _PreparedSegment:
        spoken = segment.text
        synthesis_events.append(spoken)
        return _PreparedSegment(
            offset=segment.offset,
            spoken=spoken,
            pcm=b"\x01\x00" * 100,
            audio_seconds=0.1,
            leading_silence_seconds=0.0,
            spoken_seconds=0.1,
            synthesis_ms=1,
            pause_after=segment.pause_after,
        )

    speaker._synthesize_segment = synthesize  # type: ignore[method-assign]

    speaker._speak_request(request)

    assert len(synthesis_events) > 2
    assert [event for event, _ in player.events].count("start") == 1
    assert [event for event, _ in player.events].count("finish") == 1
    assert [value for event, value in player.events if event == "silence"] == [
        pytest.approx(0.1)
    ]
    first_feed = next(
        index for index, (event, _) in enumerate(player.events) if event == "feed"
    )
    assert first_feed < len(player.events) - 1


def test_synthesis_statistics_grow_chunks_with_more_playback_runway() -> None:
    statistics = GenerationStatistics(
        synthesis_fixed_seconds=0.2,
        synthesis_seconds_per_character=0.01,
    )

    starving = statistics.choose_target_characters(0.5)
    healthy = statistics.choose_target_characters(3.0)
    full = statistics.choose_target_characters(8.0)

    assert MIN_CHUNK_CHARACTERS <= starving < healthy < full


def test_synthesis_statistics_learn_from_observed_generation() -> None:
    statistics = GenerationStatistics()
    before = statistics.choose_target_characters(3.0)

    statistics.record(text_length=100, synthesis_seconds=0.8)
    after = statistics.choose_target_characters(3.0)

    assert statistics.observations == 1
    assert after > before
