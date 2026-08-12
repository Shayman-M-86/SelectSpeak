import re
from dataclasses import dataclass

from .normalization import DISPLAY_BULLET_PREFIX, strip_display_bullet_prefix

MAX_SPEECH_SEGMENT_CHARACTERS = 100
TARGET_OVERSHOOT_RATIO = 0.35
MIN_TARGET_OVERSHOOT_CHARACTERS = 15
MAX_TARGET_OVERSHOOT_CHARACTERS = 40
_SENTENCE_END = re.compile(r"[.!?]+(?:[\"'”’)]*)\s+")
_NON_TERMINAL_ABBREVIATIONS = frozenset(
    {"dr.", "e.g.", "i.e.", "mr.", "mrs.", "ms.", "prof.", "st.", "vs."}
)



@dataclass(frozen=True, slots=True)
class SpeechSegment:
    """One backend-independent unit of speech with its display-text offset."""

    text: str
    offset: int
    pause_after: bool = True


class AdaptiveSpeechChunker:
    """Choose forward-oriented chunks while preserving display-text offsets."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._cursor = 0
        self._first = True

    @property
    def remaining_characters(self) -> int:
        return max(0, len(self._text) - self._cursor)

    def next_chunk(
        self,
        *,
        target_characters: int = 100,
        hard_max_characters: int = 500,
        max_sentences: int | None = None,
        allow_colon: bool = True,
        allow_comma: bool = False,
    ) -> SpeechSegment | None:
        self._skip_structure_prefix()
        if self._cursor >= len(self._text):
            return None

        start = self._cursor
        line_end = self._text.find("\n", start)
        forced_structure = line_end >= 0
        end = line_end if forced_structure else len(self._text)
        target = min(end, start + max(1, target_characters))
        hard_end = min(end, start + max(1, hard_max_characters))
        preferred_end = min(
            hard_end,
            start
            + target_characters
            + min(
                MAX_TARGET_OVERSHOOT_CHARACTERS,
                max(
                    MIN_TARGET_OVERSHOOT_CHARACTERS,
                    round(target_characters * TARGET_OVERSHOOT_RATIO),
                ),
            ),
        )
        strong = _boundary_positions(self._text, start, hard_end, ".!?")
        sentence_limited = False
        if max_sentences is not None and max_sentences > 0:
            if len(strong) >= max_sentences:
                sentence_end = strong[max_sentences - 1]
                sentence_limited = sentence_end < end
                hard_end = min(hard_end, sentence_end)
                target = min(target, hard_end)
                strong = [
                    position for position in strong if position <= hard_end
                ]

        if not self._first and end <= target and not sentence_limited:
            split = end
        elif self._first:
            # Latency wins for the first chunk: take the first complete sentence,
            # even when it is much shorter than the ordinary target.
            early_strong = [position for position in strong if position <= target]
            split = early_strong[0] if early_strong else self._fallback_boundary(
                start,
                target,
                hard_end,
                allow_colon=True,
                allow_comma=True,
            )
        else:
            # Later chunks accumulate complete sentences until the target,
            # without crossing the configured sentence ceiling. Prefer the
            # first strong boundary after the target, within the hard maximum.
            after_target = [position for position in strong if position >= target]
            if after_target and after_target[0] <= preferred_end:
                split = after_target[0]
            elif after_target:
                # A sentence boundary can be far beyond the synthesis budget.
                # Do not turn a small adaptive target into one giant chunk just
                # to preserve that boundary; choose a safe technical boundary.
                split = self._fallback_boundary(
                    start,
                    target,
                    preferred_end,
                    allow_colon=allow_colon,
                    allow_comma=allow_comma,
                )
            elif strong:
                split = strong[-1]
            else:
                split = self._fallback_boundary(
                    start,
                    target,
                    hard_end,
                    allow_colon=allow_colon,
                    allow_comma=allow_comma,
                )

        if forced_structure and end <= hard_end and (not strong or split >= end):
            split = end
        split = max(start + 1, min(split, hard_end))
        raw = self._text[start:split]
        trailing_end = len(raw.rstrip())
        if not trailing_end:
            self._cursor = split
            return self.next_chunk(
                target_characters=target_characters,
                hard_max_characters=hard_max_characters,
                max_sentences=max_sentences,
                allow_colon=allow_colon,
                allow_comma=allow_comma,
            )
        spoken = raw[:trailing_end]
        absolute_end = start + trailing_end
        pause_after = (
            absolute_end == end
            or spoken[-1:] in ".!?"
        )
        self._cursor = split
        self._first = False
        return SpeechSegment(spoken, start, pause_after)

    def _skip_structure_prefix(self) -> None:
        while self._cursor < len(self._text) and self._text[self._cursor].isspace():
            self._cursor += 1
        if self._text.startswith(DISPLAY_BULLET_PREFIX, self._cursor):
            self._cursor += len(DISPLAY_BULLET_PREFIX)

    def _fallback_boundary(
        self,
        start: int,
        target: int,
        hard_end: int,
        *,
        allow_colon: bool,
        allow_comma: bool,
    ) -> int:
        marks: list[str] = []
        if allow_colon:
            marks.extend((";", ":"))
        if allow_comma:
            marks.append(",")
        for mark in marks:
            candidates = _boundary_positions(
                self._text, start, hard_end, mark
            )
            if candidates:
                after_target = [
                    position for position in candidates if position >= target
                ]
                return after_target[0] if after_target else candidates[-1]

        spaces = [
            match.end()
            for match in re.finditer(r"\s+", self._text[start:hard_end])
        ]
        if spaces:
            absolute = [start + position for position in spaces]
            after_target = [position for position in absolute if position >= target]
            return after_target[0] if after_target else absolute[-1]
        return hard_end


def _boundary_positions(
    text: str, start: int, end: int, marks: str
) -> list[int]:
    if end <= start:
        return []
    escaped = re.escape(marks)
    return [
        start + match.end()
        for match in re.finditer(
            rf"[{escaped}]+(?:[\"'”’)]*)(?=\s|$)", text[start:end]
        )
    ]


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
            match.end()
            for match in re.finditer(r"[,;:]\s+|\s+", text[cursor:limit])
        ]
        split = cursor + (candidates[-1] if candidates else max_characters)
        if split <= cursor:
            split = limit
        spans.append((cursor, split))
        cursor = split
    if cursor < end:
        spans.append((cursor, end))
    return spans
