import threading

from selectspeak.speech.playback import PlaybackCommand, PlaybackController


def test_new_request_supersedes_pending_request() -> None:
    playback = PlaybackController()
    first, _active = playback.submit("First")
    second, _active = playback.submit("Second")

    assert not playback.is_current(first.generation)
    assert playback.next_request() == second


def test_completion_releases_waiter() -> None:
    playback = PlaybackController()
    request, _active = playback.submit("Read this")
    assert playback.begin(request.generation)
    result: list[bool] = []
    waiter = threading.Thread(target=lambda: result.append(playback.wait_until_done(request.generation)))
    waiter.start()

    playback.complete(request.generation)
    waiter.join(timeout=1)

    assert result == [True]


def test_pause_commands_change_shared_state_when_consumed() -> None:
    playback = PlaybackController()
    request, _active = playback.submit("Read this")
    assert playback.begin(request.generation)
    playback.consume_command()  # Clear the submit-time resume signal.

    assert playback.request_pause()
    assert playback.consume_command() is PlaybackCommand.PAUSE
    assert playback.paused
    assert playback.request_resume()
    assert playback.consume_command() is PlaybackCommand.RESUME
    assert not playback.paused
