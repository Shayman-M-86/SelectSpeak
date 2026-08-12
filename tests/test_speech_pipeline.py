from selectspeak.speech.pipeline import AdaptiveSpeechPipeline, GenerationStatistics


def test_pipeline_uses_a_meaningful_first_phrase_then_adapts_to_runway() -> None:
    text = (
        "Hi there. This next sentence is extremely long, containing several "
        "clauses, multiple explanations, and enough material to exercise the "
        "adaptive controller. A final sentence follows."
    )
    pipeline = AdaptiveSpeechPipeline(text)

    first = pipeline.choose_next()
    pressured = pipeline.choose_next(playback_runway=0.5)

    assert first is not None
    assert 80 <= len(first.segment.text) <= 135
    assert pressured is not None
    assert pressured.segment.text[-1] in ".!?;:,"
    assert pressured.target_characters < 100


def test_pipeline_combines_tiny_opening_sentences() -> None:
    text = "First. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
    statistics = GenerationStatistics(
        synthesis_fixed_seconds=0.1,
        synthesis_seconds_per_character=0.003,
    )
    pipeline = AdaptiveSpeechPipeline(text, statistics)

    first = pipeline.choose_next()
    second = pipeline.choose_next(playback_runway=5.0)
    later = pipeline.choose_next(playback_runway=5.0)

    assert first is not None
    assert first.segment.text == text
    assert second is None
    assert later is None


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


def test_second_chunk_stays_within_readability_ceiling() -> None:
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
    assert first.segment.text.endswith("paragraph,")
    assert second is not None
    assert len(second.segment.text) <= 200
    assert second.segment.text.startswith("creating approximately 2.3")
    assert third is not None
    assert third.segment.text.startswith("although you did not mark")


def test_later_chunks_follow_the_runway_model() -> None:
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
    assert len(second.segment.text) <= 200
    assert third.target_characters >= second.target_characters


def test_adaptive_chunks_have_a_readability_ceiling() -> None:
    text = " ".join(["lengthy technical explanation"] * 40)
    statistics = GenerationStatistics(
        synthesis_fixed_seconds=0.0,
        synthesis_seconds_per_character=0.001,
        observations=10,
    )
    pipeline = AdaptiveSpeechPipeline(text, statistics)

    chunks = []
    while decision := pipeline.choose_next(playback_runway=30.0):
        chunks.append(decision.segment.text)

    assert chunks
    assert max(map(len, chunks)) <= 200


def test_pipeline_does_not_force_tiny_chunks_for_short_sentences() -> None:
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
        "A sufficiently long opening sentence establishes initial runway. "
        "Second sentence is ready."
    )


def test_logged_growth_limiter_regression_uses_balanced_punctuation() -> None:
    text = (
        'The first-sentence rule accepts "Yes." unconditionally. Then the growth '
        "limiter treats 4 characters as the baseline and constrains the next "
        "request to 8, so the algorithm needs five synthesis calls to reach the "
        "colon. I’m replacing that with one simpler startup rule: choose the "
        "meaningful sentence/clause boundary closest to the startup target, "
        "ignoring trivially short boundaries when more text follows."
    )
    pipeline = AdaptiveSpeechPipeline(text)
    chunks: list[str] = []
    targets: list[int] = []

    for runway in (0.0, 2.0, 4.5, 8.0):
        decision = pipeline.choose_next(runway)
        assert decision is not None
        chunks.append(decision.segment.text)
        targets.append(decision.target_characters)
        pipeline.record_generation(
            decision.segment, 0.15 + len(decision.segment.text) * 0.0035
        )

    assert targets == [100, 120, 140, 140]
    assert [len(chunk) for chunk in chunks] == [55, 97, 113, 137]
    assert chunks[1].endswith(",")
    assert chunks[2].endswith(":")
