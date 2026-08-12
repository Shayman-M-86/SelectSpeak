import logging
import re

from ..logging_setup import log_event, text_preview

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

