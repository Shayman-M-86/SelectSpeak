from __future__ import annotations

import re
from pathlib import Path

from selectspeak.speech.normalization import (
    DISPLAY_BULLET_PREFIX,
    prepare_for_speech,
)
from selectspeak.speech.pipeline import (
    HARD_MAX_CHUNK_CHARACTERS,
    AdaptiveSpeechPipeline,
)
from selectspeak.speech.segments import (
    MIN_STARTUP_CHUNK_CHARACTERS,
    PunctuationMap,
    SpeechSegment,
)

CORPUS_PATH = Path(__file__).parent / "fixtures" / "chunking_examples.txt"
SIMULATED_RUNWAY_SECONDS = (0.0, 2.0, 4.5, 8.0)
_EXAMPLE_HEADER = re.compile(r"^\[(\d{3})\]\n")


def load_chunking_examples() -> list[tuple[str, str]]:
    examples: list[tuple[str, str]] = []
    for block in CORPUS_PATH.read_text(encoding="utf-8").split("\n---\n"):
        match = _EXAMPLE_HEADER.match(block.strip())
        assert match is not None
        examples.append((match.group(1), block.strip()[match.end() :].strip()))
    return examples


def simulate_chunks(text: str) -> tuple[str, list[SpeechSegment], list[int]]:
    prepared = prepare_for_speech(text)
    pipeline = AdaptiveSpeechPipeline(prepared)
    chunks: list[SpeechSegment] = []
    targets: list[int] = []
    index = 0
    while decision := pipeline.choose_next(
        SIMULATED_RUNWAY_SECONDS[min(index, len(SIMULATED_RUNWAY_SECONDS) - 1)]
    ):
        chunks.append(decision.segment)
        targets.append(decision.target_characters)
        simulated_synthesis = 0.15 + len(decision.segment.text) * 0.0035
        pipeline.record_generation(decision.segment, simulated_synthesis)
        index += 1
    return prepared, chunks, targets


def _canonical_spoken_text(text: str) -> str:
    without_display_bullets = re.sub(rf"(?m)^{re.escape(DISPLAY_BULLET_PREFIX)}", "", text)
    return " ".join(without_display_bullets.split())


def test_chunking_corpus_contains_one_hundred_distinct_examples() -> None:
    examples = load_chunking_examples()

    assert [identifier for identifier, _ in examples] == [f"{index:03d}" for index in range(1, 101)]
    assert len({text for _, text in examples}) == 100


def test_chunking_corpus_preserves_text_and_safe_sizes() -> None:
    problems: list[str] = []
    for identifier, text in load_chunking_examples():
        prepared, chunks, targets = simulate_chunks(text)
        observed = _canonical_spoken_text(" ".join(chunk.text for chunk in chunks))
        expected = _canonical_spoken_text(prepared)

        if observed != expected:
            problems.append(f"{identifier}: reconstructed text changed")
        if not chunks:
            problems.append(f"{identifier}: produced no chunks")
            continue
        if max(len(chunk.text) for chunk in chunks) > HARD_MAX_CHUNK_CHARACTERS:
            problems.append(f"{identifier}: exceeded {HARD_MAX_CHUNK_CHARACTERS} chars")
        if "\n" not in prepared and len(prepared) > HARD_MAX_CHUNK_CHARACTERS:
            first_length = len(chunks[0].text)
            if first_length < MIN_STARTUP_CHUNK_CHARACTERS:
                problems.append(f"{identifier}: tiny first chunk ({first_length})")
        elif len(prepared) > HARD_MAX_CHUNK_CHARACTERS:
            first_line = prepared.splitlines()[0].removeprefix(DISPLAY_BULLET_PREFIX)
            if chunks[0].text != first_line:
                problems.append(f"{identifier}: tiny start was not an intentional line boundary")
        if targets != sorted(targets):
            problems.append(f"{identifier}: targets did not grow ({targets})")

    assert not problems, "\n".join(problems)


def test_chunking_corpus_uses_whitespace_only_without_safe_punctuation() -> None:
    problems: list[str] = []
    for identifier, text in load_chunking_examples():
        prepared, chunks, _ = simulate_chunks(text)
        punctuation_map = PunctuationMap.from_text(prepared)
        for index, chunk in enumerate(chunks[:-1]):
            chunk_end = chunk.offset + len(chunk.text)
            if chunk_end in punctuation_map.boundaries or "\n" in prepared:
                continue
            start = chunk.offset
            marks = punctuation_map.punctuation_between(
                start, min(len(prepared), start + HARD_MAX_CHUNK_CHARACTERS)
            )
            if index == 0:
                marks = [position for position in marks if position - start >= MIN_STARTUP_CHUNK_CHARACTERS]
            if marks:
                problems.append(
                    f"{identifier}: chunk {index + 1} ended on whitespace "
                    f"with punctuation available at {marks}"
                )

    assert not problems, "\n".join(problems)
