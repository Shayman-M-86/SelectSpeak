import threading

from selectspeak.speech.backends.sapi import SapiSpeaker
from selectspeak.speech.playback import PlaybackController


def test_sapi_close_wakes_and_joins_worker_once() -> None:
    events: list[str] = []

    class Worker:
        def join(self) -> None:
            events.append("worker.join")

    speaker = object.__new__(SapiSpeaker)
    speaker._close_lock = threading.Lock()
    speaker._closed = False
    speaker._playback = PlaybackController()
    request, _active = speaker._playback.submit("Read this")
    assert speaker._playback.begin(request.generation)
    speaker._worker = Worker()

    speaker.close()
    speaker.close()

    assert events == ["worker.join"]
