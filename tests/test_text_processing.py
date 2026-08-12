from selectspeak.speech.normalization import (
    prepare_for_speech,
    strip_display_bullet_prefix,
)
from selectspeak.speech.segments import AdaptiveSpeechChunker, split_speech_segments


def test_prepare_for_speech_turns_each_copied_line_into_a_pause() -> None:
    assert prepare_for_speech("  hello\r\n   there\nfriend  ") == (
        "hello.\nthere.\nfriend."
    )


def test_prepare_for_speech_accepts_empty_text() -> None:
    assert prepare_for_speech("") == ""


def test_prepare_for_speech_removes_repeated_markdown_file_paths() -> None:
    text = (
        "The main implementation areas are "
        "[SurveyAccessTab.tsx]"
        "(/home/shayman86/my-repos/FlowForm/frontend/apps/studio-app/src/pages/"
        "SurveyWorkspaceTabPages/SurveyAccessTab.tsx), "
        "[RespondPage.tsx]"
        "(/home/shayman86/my-repos/FlowForm/frontend/apps/studio-app/src/pages/"
        "RespondPage.tsx), "
        "[survey_links.py]"
        "(/home/shayman86/my-repos/FlowForm/backend/app/services/"
        "survey_links.py), and "
        "[session_management.py]"
        "(/home/shayman86/my-repos/FlowForm/backend/app/services/"
        "public_submissions/api/session_management.py)."
    )

    assert prepare_for_speech(text) == (
        "The main implementation areas are SurveyAccessTab.tsx, "
        "RespondPage.tsx, survey links.py, and session management.py."
    )


def test_prepare_for_speech_shortens_raw_file_paths() -> None:
    text = (
        r"Compare /home/user/project/backend/services/survey_links.py with "
        r"C:\repos\FlowForm\frontend\src\RespondPage.tsx."
    )

    assert prepare_for_speech(text) == "Compare survey links.py with RespondPage.tsx."


def test_prepare_for_speech_replaces_underscores_with_spaces() -> None:
    assert prepare_for_speech("read_this file__name.py") == "read this file name.py"


def test_prepare_for_speech_structures_bullet_points_and_semicolons() -> None:
    text = """Tasks:
- Start the server
- Run the tests; inspect the logs
• Deploy the build"""

    assert prepare_for_speech(text) == (
        "Tasks:\n"
        "• Start the server.\n"
        "• Run the tests. inspect the logs.\n"
        "• Deploy the build."
    )


def test_prepare_for_speech_structures_numbered_points() -> None:
    text = """1. Build the package
2) Run the checks
3. Publish the result"""

    assert prepare_for_speech(text) == (
        "1. Build the package.\n2. Run the checks.\n3. Publish the result."
    )


def test_prepare_for_speech_recovers_flattened_unicode_bullets() -> None:
    assert prepare_for_speech("Checks: • Lint • Test • Build") == (
        "Checks:\n• Lint.\n• Test.\n• Build."
    )


def test_prepare_for_speech_turns_paragraph_breaks_into_pauses() -> None:
    assert prepare_for_speech("First thought\n\nSecond thought") == (
        "First thought.\nSecond thought."
    )


def test_prepare_for_speech_structures_plain_multiline_validation() -> None:
    text = """Validation
Backend focused suite: 30 passed
Studio tests: 55 passed
Studio build: passed
Studio lint: passed
Docsys tests: 11 passed"""

    assert prepare_for_speech(text) == (
        "Validation.\n"
        "• Backend focused suite: 30 passed.\n"
        "• Studio tests: 55 passed.\n"
        "• Studio build: passed.\n"
        "• Studio lint: passed.\n"
        "• Docsys tests: 11 passed."
    )


def test_prepare_for_speech_infers_bullets_when_clipboard_drops_markers() -> None:
    text = """Coverage was added for:
Private-mode access definitions.
Disabled email delivery not recording a timestamp.
Successful email delivery recording a timestamp."""

    assert prepare_for_speech(text) == (
        "Coverage was added for:\n"
        "• Private-mode access definitions.\n"
        "• Disabled email delivery not recording a timestamp.\n"
        "• Successful email delivery recording a timestamp."
    )


def test_prepare_for_speech_infers_mid_document_bullets_without_blank_lines() -> None:
    text = """Found the cause in the logs.
SelectSpeak now infers missing bullets when it sees:
A heading followed by several list-like rows
Three or more complete sentence rows
A short capitalized heading followed by rows
Explicit Markdown or Unicode bullets
The processor logs inferred bullets separately.
All checks pass."""

    assert prepare_for_speech(text) == (
        "Found the cause in the logs.\n"
        "SelectSpeak now infers missing bullets when it sees:\n"
        "• A heading followed by several list-like rows.\n"
        "• Three or more complete sentence rows.\n"
        "• A short capitalized heading followed by rows.\n"
        "• Explicit Markdown or Unicode bullets.\n"
        "The processor logs inferred bullets separately.\n"
        "All checks pass."
    )


def test_prepare_for_speech_infers_isolated_unpunctuated_list() -> None:
    text = """A heading followed by several list-like rows
Three or more complete sentence rows
A short capitalized heading followed by rows
Explicit Markdown or Unicode bullets"""

    assert prepare_for_speech(text) == (
        "• A heading followed by several list-like rows.\n"
        "• Three or more complete sentence rows.\n"
        "• A short capitalized heading followed by rows.\n"
        "• Explicit Markdown or Unicode bullets."
    )


def test_prepare_for_speech_strips_markdown_heading_and_structures_bullets() -> None:
    text = """## Validation

- Backend focused suite: 30 passed
- Studio tests: 55 passed"""

    assert prepare_for_speech(text) == (
        "Validation.\n• Backend focused suite: 30 passed.\n• Studio tests: 55 passed."
    )


def test_strip_display_bullet_prefix_preserves_highlight_offset() -> None:
    assert strip_display_bullet_prefix("• Studio tests: 55 passed.") == (
        "Studio tests: 55 passed.",
        2,
    )
    assert strip_display_bullet_prefix("Validation.") == ("Validation.", 0)


def test_prepare_for_speech_removes_rich_clipboard_object_markers() -> None:
    assert prepare_for_speech("First point.\n\ufffc\nSecond point.") == (
        "First point.\nSecond point."
    )


def test_speech_segments_split_sentences_and_preserve_display_offsets() -> None:
    text = "First sentence. Second sentence!\n• Third point. Fourth sentence?"

    segments = split_speech_segments(text)

    assert [segment.text for segment in segments] == [
        "First sentence.",
        "Second sentence!",
        "Third point.",
        "Fourth sentence?",
    ]
    displayed_segments = [
        text[segment.offset : segment.offset + len(segment.text)]
        for segment in segments
    ]
    assert displayed_segments == [
        "First sentence.",
        "Second sentence!",
        "Third point.",
        "Fourth sentence?",
    ]


def test_speech_segments_do_not_split_common_abbreviations() -> None:
    segments = split_speech_segments("Dr. Smith tested it. It worked.")

    assert [segment.text for segment in segments] == [
        "Dr. Smith tested it.",
        "It worked.",
    ]


def test_speech_segments_bound_long_run_on_text() -> None:
    text = "word " * 100

    segments = split_speech_segments(text, max_characters=40)

    assert len(segments) > 1
    assert all(len(segment.text) <= 40 for segment in segments)
    assert " ".join(segment.text for segment in segments) == text.strip()
    assert all(not segment.pause_after for segment in segments[:-1])
    assert segments[-1].pause_after


def test_adaptive_chunker_combines_a_tiny_opener_with_the_next_thought() -> None:
    chunker = AdaptiveSpeechChunker(
        "Hi there. This next sentence is deliberately much longer than the first."
    )

    first = chunker.next_chunk(target_characters=100)
    second = chunker.next_chunk(target_characters=300)

    assert first is not None
    assert first.text == (
        "Hi there. This next sentence is deliberately much longer than the first."
    )
    assert second is None


def test_adaptive_chunker_prefers_punctuation_regardless_of_runway() -> None:
    prefix = "A sufficiently complete opening sentence establishes runway. "
    text = prefix + (
        "This next sentence is extremely long, containing several clauses, "
        "multiple explanations, and enough text to require an early split"
    )
    chunker = AdaptiveSpeechChunker(text)
    chunker.next_chunk(target_characters=100, hard_max_characters=200)

    chunk = chunker.next_chunk(
        target_characters=45,
        hard_max_characters=90,
    )

    assert chunk is not None and chunk.text.endswith(",")


def test_adaptive_chunker_groups_later_complete_sentences() -> None:
    chunker = AdaptiveSpeechChunker(
        "First sentence. Second sentence. Third sentence. Fourth sentence."
    )

    first = chunker.next_chunk(target_characters=100)
    later = chunker.next_chunk(target_characters=25)

    assert first is not None
    assert first.text == (
        "First sentence. Second sentence. Third sentence. Fourth sentence."
    )
    assert later is None


def test_adaptive_chunker_does_not_force_a_tiny_two_sentence_start() -> None:
    chunker = AdaptiveSpeechChunker(
        "Opening sentence with enough words. Second sentence. Third sentence. "
        "Fourth sentence. Fifth sentence."
    )

    first = chunker.next_chunk(target_characters=100, hard_max_characters=200)
    second = chunker.next_chunk(target_characters=200, hard_max_characters=200)

    assert first is not None
    assert first.text == (
        "Opening sentence with enough words. Second sentence. Third sentence. "
        "Fourth sentence. Fifth sentence."
    )
    assert second is None


def test_adaptive_chunker_uses_whitespace_without_safe_punctuation() -> None:
    chunker = AdaptiveSpeechChunker(
        "Ready. "
        "This sentence is intentionally very long and contains enough technical "
        "detail to run far beyond a small adaptive synthesis target without any "
        "sentence punctuation that would otherwise provide a convenient split "
        "before this deliberately distant ending."
    )
    first = chunker.next_chunk(target_characters=100, hard_max_characters=200)
    second = chunker.next_chunk(
        target_characters=50,
        hard_max_characters=200,
    )

    assert first is not None
    assert 90 <= len(first.text) <= 135
    assert not first.pause_after
    assert second is not None
    assert second.text.endswith(".")
    assert second.pause_after


def test_adaptive_chunker_keeps_logged_regression_chunks_near_target() -> None:
    text = prepare_for_speech(
        "I found the actual regression: moving the native adapters changed the "
        "meaning of Path(__file__).parents[...]. Both DLL discovery functions "
        "were still calculating paths from their old locations, so the launcher "
        "could no longer find the runtime input DLL (and Natural Voice had the "
        "same latent bug). I’m replacing those fragile parent counts with one "
        "package-level runtime-path resolver."
    )
    chunker = AdaptiveSpeechChunker(text)

    first = chunker.next_chunk(target_characters=100)
    second = chunker.next_chunk(
        target_characters=30,
        hard_max_characters=60,
    )
    third = chunker.next_chunk(
        target_characters=51,
        hard_max_characters=200,
    )

    assert first is not None and 90 <= len(first.text) <= 120
    assert second is not None
    assert third is not None
    assert 46 <= len(third.text) <= 70
    assert not third.pause_after


def test_first_chunk_stays_near_target_when_first_sentence_is_long() -> None:
    text = prepare_for_speech(
        "I’ll trace **Text Grab’s actual capture/OCR path** and compare it with "
        "PowerToys Text Extractor, then I’ll reduce it to the smallest architecture "
        "that makes sense for your Python TTS app. The main thing I want to "
        "establish is whether you can call Windows’ OCR APIs directly, or whether "
        "you’d be better off embedding a tiny native helper."
    )
    chunker = AdaptiveSpeechChunker(text)

    first = chunker.next_chunk(target_characters=100, hard_max_characters=200)

    assert first is not None
    assert first.text.endswith("Extractor,")
    assert 90 <= len(first.text) <= 135
    assert not first.pause_after


def test_first_chunk_prefers_nearby_colon_over_tiny_opening_sentence() -> None:
    text = prepare_for_speech(
        "Yes. I think this is a very good candidate for the same treatment as "
        "AutoHotkey and the SAPI adapter: bring the small capability you need "
        "directly into SelectSpeak."
    )
    chunker = AdaptiveSpeechChunker(text)

    first = chunker.next_chunk(target_characters=100, hard_max_characters=200)

    assert first is not None
    assert first.text == (
        "Yes. I think this is a very good candidate for the same treatment as "
        "AutoHotkey and the SAPI adapter:"
    )


def test_adaptive_chunker_preserves_pause_after_quoted_sentence() -> None:
    text = (
        'The prompt said, "Select the paragraph and release the mouse button." '
        "A second explanation follows with enough detail to form another chunk."
    )
    chunker = AdaptiveSpeechChunker(text)

    first = chunker.next_chunk(target_characters=65, hard_max_characters=200)

    assert first is not None
    assert first.text.endswith('button."')
    assert first.pause_after
