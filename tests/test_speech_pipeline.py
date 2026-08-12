from selectspeak.speech_pipeline import (
    MIN_CHUNK_CHARACTERS,
    AdaptiveSpeechPipeline,
    GenerationStatistics,
)


def test_pipeline_uses_the_first_sentence_then_adapts_to_runway() -> None:
    text = (
        "Hi there. This next sentence is extremely long, containing several "
        "clauses, multiple explanations, and enough material to exercise the "
        "adaptive controller. A final sentence follows."
    )
    pipeline = AdaptiveSpeechPipeline(text)

    first = pipeline.choose_next()
    pressured = pipeline.choose_next(playback_runway=0.5)

    assert first is not None and first.segment.text == "Hi there."
    assert pressured is not None
    assert pressured.allow_comma
    assert pressured.target_characters < 100


def test_pipeline_ramps_after_a_very_short_first_sentence() -> None:
    text = (
        "First. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
    )
    statistics = GenerationStatistics(
        synthesis_fixed_seconds=0.1,
        synthesis_seconds_per_character=0.003,
    )
    pipeline = AdaptiveSpeechPipeline(text, statistics)

    first = pipeline.choose_next()
    second = pipeline.choose_next(playback_runway=5.0)
    later = pipeline.choose_next(playback_runway=5.0)

    assert first is not None and first.segment.text == "First."
    assert second is not None
    assert len(second.segment.text) <= len(first.segment.text) * 2
    assert later is not None
    assert later.target_characters > MIN_CHUNK_CHARACTERS
    assert later.segment.text.endswith(".")
    assert later.segment.text == "sentence. Third sentence."


def test_pipeline_shares_generation_observations_across_requests() -> None:
    statistics = GenerationStatistics()
    first = AdaptiveSpeechPipeline("One sentence.", statistics)
    decision = first.choose_next()
    assert decision is not None
    first.record_generation(decision.segment, 0.4)

    second = AdaptiveSpeechPipeline("Another sentence.", statistics)

    assert second.statistics is statistics
    assert second.statistics.observations == 1


def test_chunk_decision_includes_the_predicted_synthesis_time() -> None:
    statistics = GenerationStatistics(
        synthesis_fixed_seconds=0.2,
        synthesis_seconds_per_character=0.01,
    )
    pipeline = AdaptiveSpeechPipeline("A short sentence.", statistics)

    decision = pipeline.choose_next()

    assert decision is not None
    assert decision.predicted_synthesis_seconds == (
        0.2 + len(decision.segment.text) * 0.01
    )


def test_second_chunk_cannot_be_more_than_twice_the_first_chunk() -> None:
    text = (
        "The same underrun occurred between Löfgren pattern. "
        "and the second paragraph, creating approximately 2.3 seconds of audible "
        "silence, although you did not mark that paragraph break as unexpected."
    )
    pipeline = AdaptiveSpeechPipeline(text)

    first = pipeline.choose_next()
    second = pipeline.choose_next(playback_runway=2.225)
    third = pipeline.choose_next(playback_runway=5.0)

    assert first is not None
    assert first.segment.text == (
        "The same underrun occurred between Löfgren pattern."
    )
    assert second is not None
    assert second.segment.text.endswith("audible silence,")
    assert len(second.segment.text) <= len(first.segment.text) * 2
    assert third is not None
    assert third.segment.text.startswith("although you did not mark that")


def test_later_chunks_can_grow_beyond_the_startup_ratio() -> None:
    text = (
        "A short opening sentence. "
        "A second sentence with enough words, and another clause to force an "
        "early startup split before its eventual ending. "
        "Later chunks may combine this complete sentence with another complete "
        "sentence when playback runway is healthy. One more sentence follows."
    )
    statistics = GenerationStatistics(
        synthesis_fixed_seconds=0.1,
        synthesis_seconds_per_character=0.002,
    )
    pipeline = AdaptiveSpeechPipeline(text, statistics)

    first = pipeline.choose_next()
    second = pipeline.choose_next(playback_runway=1.0)
    third = pipeline.choose_next(playback_runway=8.0)

    assert first is not None and second is not None and third is not None
    assert len(second.segment.text) <= len(first.segment.text) * 2
    assert len(third.segment.text) > len(second.segment.text) * 2


def test_pipeline_never_groups_more_than_two_complete_sentences() -> None:
    text = (
        "A sufficiently long opening sentence establishes initial runway. "
        "Second sentence is ready. Third sentence is ready. "
        "Fourth sentence is ready. Fifth sentence is ready."
    )
    statistics = GenerationStatistics(
        synthesis_fixed_seconds=0.1,
        synthesis_seconds_per_character=0.001,
    )
    pipeline = AdaptiveSpeechPipeline(text, statistics)

    chunks = []
    while decision := pipeline.choose_next(playback_runway=20.0):
        chunks.append(decision.segment.text)

    assert chunks[0] == (
        "A sufficiently long opening sentence establishes initial runway."
    )
    assert all(chunk.count(".") <= 2 for chunk in chunks)
    assert chunks[1] == "Second sentence is ready. Third sentence is ready."
