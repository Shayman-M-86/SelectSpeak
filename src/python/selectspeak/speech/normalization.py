import logging
import re

from ..diagnostics import text_preview

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
_EMBEDDED_OBJECTS = re.compile("[\ufffc\ufffd]")
_EMBEDDED_OBJECT_LINE = re.compile(r"(?m)^[ \t]*(?:[\uFFFC\uFFFD][ \t]*)+\n?")
_TERMINAL_PUNCTUATION = frozenset(".?!:")
# Shorter lines than this read as deliberate standalone lines (list items,
# labels, short headings) rather than the product of a hard wrap.
_WRAPPED_LINE_MIN_LENGTH = 40
DISPLAY_BULLET_PREFIX = "• "


def prepare_for_speech(text: str) -> str:
    """Normalize copied structure and noisy paths into speech-friendly prose."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    embedded_object_count = len(_EMBEDDED_OBJECTS.findall(normalized))
    without_object_lines = _EMBEDDED_OBJECT_LINE.sub("", normalized)
    without_objects = _EMBEDDED_OBJECTS.sub("", without_object_lines)
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
    logger.debug(
        "text.prepared_for_speech input_length=%s output_length=%s "
        "input_preview=%s output_preview=%s markdown_links_removed=%s "
        "paths_shortened=%s bullets_structured=%s bullets_inferred=%s "
        "markdown_headings_removed=%s line_breaks_structured=%s "
        "paragraph_breaks_structured=%s semicolons_strengthened=%s "
        "underscores_replaced=%s embedded_objects_removed=%s",
        len(text),
        len(result),
        text_preview(text),
        text_preview(result),
        markdown_link_count,
        windows_path_count + posix_path_count + relative_path_count,
        bullet_count,
        inferred_bullet_count,
        heading_count,
        line_break_count,
        paragraph_count,
        semicolon_count,
        underscore_count,
        embedded_object_count,
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
    pending_paragraph_break = False

    lines = text.split("\n")
    inferred_bullet_lines = _infer_bullet_lines(lines)
    structured_multiline = sum(bool(line.strip()) for line in lines) > 1
    for index, line in enumerate(lines):
        if not line.strip():
            if (
                segments
                and not pending_paragraph_break
                and any(remaining.strip() for remaining in lines[index + 1 :])
            ):
                paragraph_count += 1
                pending_paragraph_break = True
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
            spoken_line = f"{numbered_match.group(1)}. {_collapse_whitespace(numbered_match.group(2))}"
            bullet_count += 1
        elif index in inferred_bullet_lines:
            spoken_line = f"{DISPLAY_BULLET_PREFIX}{line}"
            inferred_bullet_count += 1
        else:
            spoken_line = line

        spoken_line = _collapse_whitespace(spoken_line)
        if spoken_line:
            is_explicit_structure = bool(heading_match or bullet_match or numbered_match)
            next_line = next(
                (candidate.strip() for candidate in lines[index + 1 :] if candidate.strip()),
                None,
            )
            # Explicit structure ends a thought by construction; wrapped prose
            # does not, so never break a sentence that continues on the next
            # line.
            if is_explicit_structure or (
                structured_multiline and not _continues_on_next_line(spoken_line, next_line)
            ):
                spoken_line = _ensure_pause(spoken_line)
            if pending_paragraph_break and segments and segments[-1] != "":
                segments.append("")
            segments.append(spoken_line)
            pending_paragraph_break = False

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
        if any(_BULLET_LINE.match(line) or _NUMBERED_LINE.match(line) for line in block_lines):
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
        elif all(line[:1].isupper() and line[-1:] not in ".?!:" for line in block_lines):
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


def _continues_on_next_line(line: str, next_line: str | None) -> bool:
    """Return whether a hard wrap split one sentence across two lines.

    Prose pasted from a wrapped document (source comments, docstrings, commit
    bodies) breaks mid-sentence, so a line ending is not a thought ending.
    Adding a pause there makes speech stop in the middle of a clause. Short
    standalone lines - list items, labels, headings - are the opposite case and
    still want their pause, so only treat a break as a wrap when the line is
    long enough to have been wrapped and the next one resumes in lower case.
    """
    if next_line is None:
        return False
    if not line or line[-1] in _TERMINAL_PUNCTUATION or line[-1] in ",;":
        # A clause-final comma still reads as a continuation, but the existing
        # punctuation already supplies the pause, so nothing needs adding.
        return line[-1:] in ",;"
    if len(line) < _WRAPPED_LINE_MIN_LENGTH:
        return False
    return next_line[:1].islower()


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s{2,}", " ", text).strip()
