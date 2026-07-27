from selectspeak.text_processing import prepare_for_speech, strip_display_bullet_prefix


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
