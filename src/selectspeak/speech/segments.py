from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from .normalization import DISPLAY_BULLET_PREFIX, strip_display_bullet_prefix

MAX_SPEECH_SEGMENT_CHARACTERS = 100
MAX_ADAPTIVE_CHUNK_CHARACTERS = 200
MIN_STARTUP_CHUNK_CHARACTERS = 50
_SENTENCE_END = re.compile(r"[.!?]+(?:[\"'”’)]*)\s+")
_ADAPTIVE_BOUNDARY = re.compile(r"[.!?;:,]+(?:[\"'”’)]*)(?=\s|$)")
_NON_TERMINAL_ABBREVIATIONS = frozenset(
    {"dr.", "e.g.", "i.e.", "mr.", "mrs.", "ms.", "prof.", "st.", "vs."}
)


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    """One backend-independent unit of speech with its display-text offset."""

    text: str
    offset: int
    pause_after: bool = True


@dataclass(frozen=True, slots=True)
class PunctuationMap:
    """Punctuation offsets indexed once for adaptive chunk selection."""

    boundaries: tuple[int, ...]
    sentence_boundaries: frozenset[int]

    @classmethod
    def from_text(cls, text: str) -> PunctuationMap:
        boundaries: list[int] = []
        sentence_boundaries: set[int] = set()
        for match in _ADAPTIVE_BOUNDARY.finditer(text):
            boundaries.append(match.end())
            if any(mark in match.group() for mark in ".!?"):
                sentence_boundaries.add(match.end())
        return cls(tuple(boundaries), frozenset(sentence_boundaries))

    def punctuation_between(self, start: int, end: int) -> list[int]:
        return _positions_between(self.boundaries, start, end)


class AdaptiveSpeechChunker:
    """Choose adaptive sizes using a punctuation map built once per text."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._punctuation = PunctuationMap.from_text(text)
        self._cursor = 0
        self._first = True

    @property
    def remaining_characters(self) -> int:
        return max(0, len(self._text) - self._cursor)

    def next_chunk(
        self,
        *,
        target_characters: int = 100,
        hard_max_characters: int = MAX_ADAPTIVE_CHUNK_CHARACTERS,
    ) -> SpeechSegment | None:
        self._skip_structure_prefix()
        if self._cursor >= len(self._text):
            return None

        start = self._cursor
        line_end = self._text.find("\n", start)
        end = line_end if line_end >= 0 else len(self._text)
        target = min(end, start + max(1, target_characters))
        hard_end = min(end, start + max(1, hard_max_characters))

        if not self._first and end <= target:
            split = end
        else:
            candidates = self._punctuation.punctuation_between(start, hard_end)
            if self._first:
                # A tiny opener such as "Yes." is not a useful startup chunk.
                meaningful = [
                    position
                    for position in candidates
                    if position - start >= MIN_STARTUP_CHUNK_CHARACTERS
                ]
                candidates = meaningful
            if candidates:
                split = min(
                    candidates, key=lambda position: abs(position - target)
                )
            elif end <= hard_end:
                split = end
            else:
                split = self._whitespace_boundary(start, target, hard_end)

        split = max(start + 1, min(split, hard_end))
        raw = self._text[start:split]
        trailing_end = len(raw.rstrip())
        if not trailing_end:
            self._cursor = split
            return self.next_chunk(
                target_characters=target_characters,
                hard_max_characters=hard_max_characters,
            )
        spoken = raw[:trailing_end]
        absolute_end = start + trailing_end
        pause_after = (
            absolute_end == end or absolute_end in self._punctuation.sentence_boundaries
        )
        self._cursor = split
        self._first = False
        return SpeechSegment(spoken, start, pause_after)

    def _skip_structure_prefix(self) -> None:
        while self._cursor < len(self._text) and self._text[self._cursor].isspace():
            self._cursor += 1
        if self._text.startswith(DISPLAY_BULLET_PREFIX, self._cursor):
            self._cursor += len(DISPLAY_BULLET_PREFIX)

    def _whitespace_boundary(self, start: int, target: int, hard_end: int) -> int:
        spaces = [
            match.end() for match in re.finditer(r"\s+", self._text[start:hard_end])
        ]
        if spaces:
            absolute = [start + position for position in spaces]
            after_target = [position for position in absolute if position >= target]
            return after_target[0] if after_target else absolute[-1]
        return hard_end


def _positions_between(positions: tuple[int, ...], start: int, end: int) -> list[int]:
    first = bisect_right(positions, start)
    last = bisect_right(positions, end)
    return list(positions[first:last])


def split_speech_segments(
    text: str, max_characters: int = MAX_SPEECH_SEGMENT_CHARACTERS
) -> list[SpeechSegment]:
    """Split prepared text consistently at lines, sentences, then safe clauses."""
    segments: list[SpeechSegment] = []
    for line_match in re.finditer(r"[^\n]+", text):
        line = line_match.group()
        spoken, prefix = strip_display_bullet_prefix(line)
        spoken_offset = line_match.start() + prefix
        for start, end in _sentence_spans(spoken):
            chunks = _bounded_spans(spoken, start, end, max_characters)
            for chunk_index, (chunk_start, chunk_end) in enumerate(chunks):
                chunk = spoken[chunk_start:chunk_end]
                leading = len(chunk) - len(chunk.lstrip())
                trailing_end = len(chunk.rstrip())
                if trailing_end > leading:
                    segments.append(
                        SpeechSegment(
                            chunk[leading:trailing_end],
                            spoken_offset + chunk_start + leading,
                            pause_after=chunk_index == len(chunks) - 1,
                        )
                    )
    return segments


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        # Keep terminal punctuation but not the following whitespace.
        end = match.start() + len(match.group().rstrip())
        preceding_word = text[start:end].rsplit(maxsplit=1)[-1].casefold()
        if preceding_word in _NON_TERMINAL_ABBREVIATIONS:
            continue
        spans.append((start, end))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _bounded_spans(
    text: str, start: int, end: int, max_characters: int
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > max_characters:
        limit = cursor + max_characters
        candidates = [
            match.end() for match in re.finditer(r"[,;:]\s+|\s+", text[cursor:limit])
        ]
        split = cursor + (candidates[-1] if candidates else max_characters)
        if split <= cursor:
            split = limit
        spans.append((cursor, split))
        cursor = split
    if cursor < end:
        spans.append((cursor, end))
    return spans
