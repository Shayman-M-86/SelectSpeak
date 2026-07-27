from selectspeak.text import tidy_text


def test_tidy_text_collapses_line_breaks_and_repeated_whitespace() -> None:
    assert tidy_text("  hello\r\n   there\nfriend  ") == "hello there friend"


def test_tidy_text_accepts_empty_text() -> None:
    assert tidy_text("") == ""
