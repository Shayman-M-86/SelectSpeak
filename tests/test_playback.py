import threading
from collections.abc import Callable
from queue import Empty

import pytest

from selectspeak.speech.contracts import (
    SpeechEvent,
    SpeechStarted,
    SpeechTerminal,
    SpeechWord,
    TerminalStatus,
)
from selectspeak.speech.playback import UINT64_MAX, PlaybackCommand, PlaybackController


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[SpeechEvent] = []
        self.changed = threading.Condition()

    def __call__(self, event: SpeechEvent) -> None:
        with self.changed:
            self.events.append(event)
            self.changed.notify_all()

    def wait_for(self, count: int) -> None:
        with self.changed:
            assert self.changed.wait_for(lambda: len(self.events) >= count, timeout=1)


def test_new_request_supersedes_pending_request_in_event_order() -> None:
    playback = PlaybackController()
    events = EventRecorder()
    first, _active = playback.submit(10, "First", events)
    second, _active = playback.submit(11, "Second", events)

    events.wait_for(3)
    assert events.events == [
        SpeechStarted(10),
        SpeechTerminal(10, TerminalStatus.SUPERSEDED),
        SpeechStarted(11),
    ]
    assert not playback.is_current(first.generation)
    assert playback.next_request() == second
    playback.close()


def test_completion_delivers_words_then_exactly_one_terminal() -> None:
    playback = PlaybackController()
    events = EventRecorder()
    request, _active = playback.submit(1, "Read this", events)
    assert playback.next_request() == request

    playback.played_word(request.generation, 0, 4)
    playback.complete(request.generation)
    playback.complete(request.generation)

    events.wait_for(3)
    assert events.events == [
        SpeechStarted(1),
        SpeechWord(1, "Read this", 0, 4),
        SpeechTerminal(1, TerminalStatus.COMPLETED),
    ]
    playback.played_word(request.generation, 5, 4)
    playback.close()
    assert len(events.events) == 3


def test_pause_commands_change_shared_state_when_consumed() -> None:
    playback = PlaybackController()
    request, _active = playback.submit(1, "Read this", lambda _event: None)
    assert playback.next_request() == request

    assert playback.request_pause()
    assert playback.consume_command() is PlaybackCommand.PAUSE
    assert playback.paused
    assert playback.request_resume()
    assert playback.consume_command() is PlaybackCommand.RESUME
    assert not playback.paused
    playback.close()


def test_close_rejects_new_work_wakes_worker_and_emits_closed() -> None:
    playback = PlaybackController()
    events = EventRecorder()
    request, _active = playback.submit(1, "Read this", events)
    assert playback.next_request() == request

    assert playback.close()

    assert playback.next_request() is None
    assert events.events == [
        SpeechStarted(1),
        SpeechTerminal(1, TerminalStatus.CLOSED),
    ]
    with pytest.raises(RuntimeError, match="speech backend is closed"):
        playback.submit(2, "Too late", events)


def test_close_wakes_a_worker_blocked_for_the_next_request() -> None:
    playback = PlaybackController()
    waiting = threading.Event()
    result: list[object] = []

    def wait_for_request() -> None:
        waiting.set()
        result.append(playback.next_request())

    worker = threading.Thread(target=wait_for_request)
    worker.start()
    assert waiting.wait(timeout=1)

    assert not playback.close()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert result == [None]


def test_failure_wakes_a_worker_blocked_for_the_next_request() -> None:
    playback = PlaybackController()
    waiting = threading.Event()
    result: list[object] = []

    def wait_for_request() -> None:
        waiting.set()
        result.append(playback.next_request())

    worker = threading.Thread(target=wait_for_request)
    worker.start()
    assert waiting.wait(timeout=1)

    playback.fail()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert result == [None]
    with pytest.raises(RuntimeError, match="speech worker has failed"):
        playback.submit(1, "Too late", lambda _event: None)
    playback.close()


def test_next_request_timeout_matches_queue_contract() -> None:
    playback = PlaybackController()

    with pytest.raises(Empty):
        playback.next_request(timeout=0)

    playback.close()


def test_superseding_request_clears_pending_control_command() -> None:
    playback = PlaybackController()
    first, _active = playback.submit(1, "First", lambda _event: None)
    assert playback.next_request() == first
    assert playback.request_pause()

    second, _active = playback.submit(2, "Second", lambda _event: None)

    assert playback.next_request() == second
    assert playback.consume_command() is PlaybackCommand.NONE
    playback.close()


def test_event_callback_can_cancel_its_request_without_deadlocking() -> None:
    playback = PlaybackController()
    events: list[SpeechEvent] = []

    def cancel_on_start(event: SpeechEvent) -> None:
        events.append(event)
        if isinstance(event, SpeechStarted):
            playback.cancel()

    playback.submit(1, "Read this", cancel_on_start)

    assert events == [
        SpeechStarted(1),
        SpeechTerminal(1, TerminalStatus.CANCELLED),
    ]
    with pytest.raises(Empty):
        playback.next_request(timeout=0)
    playback.close()


@pytest.mark.parametrize("request_id", [0, -1, UINT64_MAX + 1])
def test_request_id_must_fit_nonzero_uint64(request_id: int) -> None:
    playback = PlaybackController()
    with pytest.raises(ValueError, match="unsigned 64-bit"):
        playback.submit(request_id, "Read this", lambda _event: None)
    playback.close()


def test_request_id_must_increase_for_each_backend() -> None:
    playback = PlaybackController()
    playback.submit(5, "Read this", lambda _event: None)
    with pytest.raises(ValueError, match="increase monotonically"):
        playback.submit(5, "Read again", lambda _event: None)
    playback.close()


@pytest.mark.parametrize(
    ("action", "status"),
    [
        (lambda playback, generation: playback.cancel(), TerminalStatus.CANCELLED),
        (lambda playback, generation: playback.fail(generation), TerminalStatus.FAILED),
    ],
)
def test_non_success_terminal_statuses_are_delivered_once(
    action: Callable[[PlaybackController, int], object],
    status: TerminalStatus,
) -> None:
    playback = PlaybackController()
    events = EventRecorder()
    request, _active = playback.submit(1, "Read this", events)
    assert playback.next_request() == request

    action(playback, request.generation)
    playback.complete(request.generation)
    events.wait_for(2)

    assert events.events == [SpeechStarted(1), SpeechTerminal(1, status)]
    playback.close()
