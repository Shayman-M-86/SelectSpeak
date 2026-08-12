import logging
import re
from dataclasses import dataclass

from .logging_setup import log_event, text_preview

logger = logging.getLogger(__name__)

_MARKDOWN_LINK = re.compile(r"!?\[([^\]\r\n]+)\]\(([^)\r\n]+)\)")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\(?:[^\\\s,;:()\[\]]+\\){1,}[^\\\s,;:()\[\]]+")
_POSIX_PATH = re.compile(r"(?<![/:])/(?:[^/\s,;:()\[\]]+/){2,}[^/\s,;:()\[\]]+")
_RELATIVE_PATH = re.compile(r"(?<![/:])\b(?:[A-Za-z0-9_.-]+/){3,}[A-Za-z0-9_.-]+\b")
_INLINE_UNICODE_BULLET = re.compile(r"\s+([•‣◦▪●])\s+")
_BULLET_LINE = re.compile(r"^\s*([-*+•‣◦▪●])\s+(.+?)\s*$")
_NUMBERED_LINE = re.compile(r"^\s*(\d+)[.)]\s+(.+?)\s*$")
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_SEMICOLON = re.compile(r"\s*;\s*")
_UNDERSCORES = re.compile(r"_+")
_EMBEDDED_OBJECTS = re.compile("[\uFFFC\uFFFD]")
_TERMINAL_PUNCTUATION = frozenset(".?!:")
DISPLAY_BULLET_PREFIX = "• "
MAX_SPEECH_SEGMENT_CHARACTERS = 100
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
            if after_target:
                split = after_target[0]
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


def prepare_for_speech(text: str) -> str:
    """Normalize copied structure and noisy paths into speech-friendly prose."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    without_objects, embedded_object_count = _EMBEDDED_OBJECTS.subn("", normalized)
    without_links, markdown_link_count = _MARKDOWN_LINK.subn(r"\1", without_objects)
    shortened, windows_path_count = _WINDOWS_PATH.subn(_path_basename, without_links)
    shortened, posix_path_count = _POSIX_PATH.subn(_path_basename, shortened)
    shortened, relative_path_count = _RELATIVE_PATH.subn(_path_basename, shortened)
    without_underscores, underscore_count = _UNDERSCORES.subn(" ", shortened)
    with_pauses, semicolon_count = _SEMICOLON.subn(". ", without_underscores)
    restored_bullets = _INLINE_UNICODE_BULLET.sub(r"\n\1 ", with_pauses)
    (
        result,
        bullet_count,
        inferred_bullet_count,
        heading_count,
        line_break_count,
        paragraph_count,
    ) = _structure_lines(restored_bullets)
    log_event(
        logger,
        logging.DEBUG,
        "text.prepared_for_speech",
        input_length=len(text),
        output_length=len(result),
        input_preview=text_preview(text),
        output_preview=text_preview(result),
        markdown_links_removed=markdown_link_count,
        paths_shortened=(windows_path_count + posix_path_count + relative_path_count),
        bullets_structured=bullet_count,
        bullets_inferred=inferred_bullet_count,
        markdown_headings_removed=heading_count,
        line_breaks_structured=line_break_count,
        paragraph_breaks_structured=paragraph_count,
        semicolons_strengthened=semicolon_count,
        underscores_replaced=underscore_count,
        embedded_objects_removed=embedded_object_count,
    )
    return result


def strip_display_bullet_prefix(segment: str) -> tuple[str, int]:
    """Return speakable segment text and its display-only prefix length."""
    if segment.startswith(DISPLAY_BULLET_PREFIX):
        return (
            segment[len(DISPLAY_BULLET_PREFIX) :],
            len(DISPLAY_BULLET_PREFIX),
        )
    return segment, 0


def _path_basename(match: re.Match[str]) -> str:
    return match.group(0).replace("\\", "/").rsplit("/", 1)[-1]


def _structure_lines(text: str) -> tuple[str, int, int, int, int, int]:
    segments: list[str] = []
    bullet_count = 0
    inferred_bullet_count = 0
    heading_count = 0
    line_break_count = 0
    paragraph_count = 0

    lines = text.split("\n")
    inferred_bullet_lines = _infer_bullet_lines(lines)
    structured_multiline = sum(bool(line.strip()) for line in lines) > 1
    for index, line in enumerate(lines):
        if not line.strip():
            if segments and any(remaining.strip() for remaining in lines[index + 1 :]):
                paragraph_count += 1
            continue

        if segments:
            line_break_count += 1

        heading_match = _MARKDOWN_HEADING.match(line)
        bullet_match = _BULLET_LINE.match(line)
        numbered_match = _NUMBERED_LINE.match(line)
        if heading_match:
            spoken_line = heading_match.group(1)
            heading_count += 1
        elif bullet_match:
            spoken_line = f"{DISPLAY_BULLET_PREFIX}{bullet_match.group(2)}"
            bullet_count += 1
        elif numbered_match:
            spoken_line = (
                f"{numbered_match.group(1)}. "
                f"{_collapse_whitespace(numbered_match.group(2))}"
            )
            bullet_count += 1
        elif index in inferred_bullet_lines:
            spoken_line = f"{DISPLAY_BULLET_PREFIX}{line}"
            inferred_bullet_count += 1
        else:
            spoken_line = line

        spoken_line = _collapse_whitespace(spoken_line)
        if spoken_line:
            is_explicit_structure = bool(
                heading_match or bullet_match or numbered_match
            )
            if structured_multiline or is_explicit_structure:
                spoken_line = _ensure_pause(spoken_line)
            segments.append(spoken_line)

    return (
        "\n".join(segments).strip(),
        bullet_count,
        inferred_bullet_count,
        heading_count,
        line_break_count,
        paragraph_count,
    )


def _infer_bullet_lines(lines: list[str]) -> set[int]:
    inferred: set[int] = set()
    block: list[int] = []

    for index, line in enumerate(lines):
        if not line.strip().endswith(":"):
            continue
        candidates: list[int] = []
        for candidate_index in range(index + 1, len(lines)):
            candidate = lines[candidate_index].strip()
            if not candidate:
                continue
            if candidate[-1:] in ".?!:":
                break
            if _BULLET_LINE.match(candidate) or _NUMBERED_LINE.match(candidate):
                break
            candidates.append(candidate_index)
        if len(candidates) >= 2:
            inferred.update(candidates)

    def classify_block() -> None:
        if len(block) < 3:
            return
        block_lines = [lines[index].strip() for index in block]
        if any(
            _BULLET_LINE.match(line) or _NUMBERED_LINE.match(line)
            for line in block_lines
        ):
            return

        first_line = block_lines[0]
        first_is_heading = (
            first_line.endswith(":")
            or (
                first_line[:1].isupper()
                and first_line[-1:] not in ".?!:"
                and all(line[-1:] in ".?!" for line in block_lines[1:])
            )
            or (
                " " not in first_line
                and first_line[:1].isupper()
                and all(":" in line for line in block_lines[1:])
            )
        )
        if first_is_heading:
            inferred.update(block[1:])
        elif all(line[-1:] in ".?!" for line in block_lines):
            inferred.update(block)
        elif all(
            line[:1].isupper() and line[-1:] not in ".?!:" for line in block_lines
        ):
            inferred.update(block)

    for index, line in enumerate(lines):
        if line.strip():
            block.append(index)
        else:
            classify_block()
            block.clear()
    classify_block()
    return inferred


def _ensure_pause(text: str) -> str:
    if text and text[-1] not in _TERMINAL_PUNCTUATION:
        return f"{text}."
    return text


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s{2,}", " ", text).strip()
