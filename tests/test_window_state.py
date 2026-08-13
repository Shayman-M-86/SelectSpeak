from selectspeak.ui.window_state import _Rect, rectangle_covers_monitor


def test_fullscreen_rectangle_covers_monitor() -> None:
    monitor = _Rect(0, 0, 1920, 1080)

    assert rectangle_covers_monitor(_Rect(0, 0, 1920, 1080), monitor)
    assert rectangle_covers_monitor(_Rect(-1, -1, 1921, 1081), monitor)


def test_maximized_work_area_is_not_treated_as_fullscreen() -> None:
    monitor = _Rect(0, 0, 1920, 1080)

    assert not rectangle_covers_monitor(_Rect(0, 0, 1920, 1040), monitor)
