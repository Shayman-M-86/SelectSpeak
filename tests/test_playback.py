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


def test_close_rejects_new_work_and_wakes_worker_and_waiter() -> None:
    playback = PlaybackController()
    request, _active = playback.submit("Read this")
    assert playback.begin(request.generation)
    waiter_result: list[bool] = []
    waiter = threading.Thread(
        target=lambda: waiter_result.append(playback.wait_until_done(request.generation))
    )
    waiter.start()

    assert playback.close()
    waiter.join(timeout=1)

    assert waiter_result == [False]
    assert playback.next_request() is None
    try:
        playback.submit("Too late")
    except RuntimeError as error:
        assert str(error) == "The speech backend is closed"
    else:
        raise AssertionError("closed playback accepted a request")
