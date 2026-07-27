from selectspeak.autohotkey import build_sidecar_script


def test_sidecar_captures_before_waiting_for_physical_release() -> None:
    script = build_sidecar_script("alt+s")

    assert "$!s::CaptureSelection(true)" in script
    assert 'A_MenuMaskKey := "vkE8"' in script
    assert '"{Blind}{LControl up}{RControl up}{LAlt up}{RAlt up}"' in script
    assert '"{Ctrl down}c{Ctrl up}"' in script
    assert script.index("SendEvent") < script.index('KeyWait "s"')


def test_sidecar_exposes_the_same_capture_for_application_requests() -> None:
    script = build_sidecar_script("alt+s")

    assert "SetTimer(CheckForCaptureRequest, 50)" in script
    assert "CaptureSelection(false)" in script
    assert script.count("SendEvent") == 1


def test_sidecar_restores_clipboard_before_signalling_python() -> None:
    script = build_sidecar_script("alt+s")

    assert script.index("A_Clipboard := savedClipboard") < script.index('"CAPTURED`t"')
