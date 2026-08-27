"""Choosing and loading the speech engine behind the selected voice.

Switching voice is the one action here that cannot happen inline: a Natural
Voice has to be initialised, and Supertonic may need its model loaded or its
whole dependency layer installed first. So it runs on its own thread, holds its
own "a switch is in progress" state, and the rest of the application asks
whether it is busy rather than tracking it.

The controller owns every speaker and is the sole source of the current one.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from dataclasses import replace

from ..config import AppConfig
from ..speech import Speaker, create_speaker
from ..speech.backends.natural import NaturalVoiceSpeaker, discover_natural_voices
from ..speech.debug import SpeechDebugCallback
from ..speech.supertonic_setup import is_ready as supertonic_is_ready
from ..speech.supertonic_setup import launch_installer as launch_supertonic_installer
from ..speech.voices import VoiceOption, build_voice_options, natural_voice_key, supertonic_voice_key
from ..ui.contracts import Player

logger = logging.getLogger(__name__)

BACKEND_INSTALLING = "installing"
BACKEND_LOADING = "loading"

MESSAGE_BOX_YES_NO = 0x00000004
MESSAGE_BOX_ICON_QUESTION = 0x00000020
MESSAGE_BOX_YES = 6


def confirm_supertonic_install() -> bool:
    """Ask before handing control to setup for the large optional component."""
    windows_libraries = getattr(ctypes, "windll", None)
    if windows_libraries is None:
        return False
    result = windows_libraries.user32.MessageBoxW(
        None,
        "Supertonic Neural Voice is not installed.\n\n"
        "Setup will add its Python dependencies and local voice model, requiring "
        "approximately 475 MB. SelectSpeak will restart when setup finishes.\n\n"
        "Install Supertonic now?",
        "Install Supertonic Neural Voice",
        MESSAGE_BOX_YES_NO | MESSAGE_BOX_ICON_QUESTION,
    )
    return result == MESSAGE_BOX_YES


def speaker_backend(speaker: Speaker) -> str:
    """Name the backend a speaker came from, for settings and the voice list."""
    if isinstance(speaker, NaturalVoiceSpeaker):
        return "natural"
    name = type(speaker).__name__.casefold()
    if "supertonic" in name:
        return "supertonic"
    raise TypeError(f"Unsupported SelectSpeak speaker: {type(speaker).__name__}")


class VoiceController:
    """Own voice selection, engine loading and the Supertonic install handoff.

    ``on_activated`` receives the backend and config for a voice that finished
    loading; the application persists settings but never owns the speaker.
    ``on_stop_playback`` is called before a switch, because the engine that is
    speaking is about to be replaced.
    """

    def __init__(
        self,
        config: AppConfig,
        player: Player,
        *,
        debug_callback: SpeechDebugCallback,
        on_activated: Callable[[str, str, AppConfig], None],
        on_stop_playback: Callable[[], None],
        on_shutdown_requested: Callable[[], None],
    ) -> None:
        self._config = config
        self._player = player
        self._debug_callback = debug_callback
        self._on_activated = on_activated
        self._on_stop_playback = on_stop_playback
        self._on_shutdown_requested = on_shutdown_requested

        self._lock = threading.RLock()
        self._speakers: dict[str, Speaker] = {}
        self._options: dict[str, VoiceOption] = {}
        self._selected_key = ""
        self._current_backend = ""
        self._switching = False
        self._activity = ""
        self._closed = False
        self._worker: threading.Thread | None = None

    # -- state the application layer asks about ----------------------------

    @property
    def switching(self) -> bool:
        with self._lock:
            return self._switching

    @property
    def activity(self) -> str:
        """What the in-progress switch is doing, for the message shown."""
        with self._lock:
            return self._activity or BACKEND_LOADING

    @property
    def speaker(self) -> Speaker:
        with self._lock:
            if not self._current_backend:
                raise RuntimeError("Voice controller has not been started")
            return self._speakers[self._current_backend]

    @property
    def backend(self) -> str:
        with self._lock:
            if not self._current_backend:
                raise RuntimeError("Voice controller has not been started")
            return self._current_backend

    def close(self) -> None:
        """Reject switches, settle the loader, then close every owned speaker."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join()
        with self._lock:
            speakers = tuple(self._speakers.values())
            self._speakers.clear()
            self._current_backend = ""
            self._switching = False
            self._activity = ""
        for speaker in speakers:
            try:
                speaker.close()
            except Exception:
                logger.exception("speaker.close_failed backend=%s", speaker_backend(speaker))
        logger.info("speaker.controller.closed speaker_count=%s", len(speakers))

    # -- startup -----------------------------------------------------------

    def start(self) -> None:
        """Create, own, and publish the configured initial speaker."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Voice controller is closed")
            config = self._config
        speaker = create_speaker(config, self._debug_callback)
        backend = speaker_backend(speaker)
        with self._lock:
            if self._closed:
                speaker.close()
                raise RuntimeError("Voice controller closed during startup")
            self._speakers[backend] = speaker
            self._current_backend = backend
        self.publish_options(speaker, backend)
        if isinstance(speaker, NaturalVoiceSpeaker):
            selected_key = natural_voice_key(speaker.voice.package_path, speaker.voice.name)
            selected_config = replace(
                config,
                speech_backend="natural",
                preferred_voice_match=selected_key,
            )
            with self._lock:
                self._config = selected_config
            self._on_activated("natural", selected_key, selected_config)

    def publish_options(self, speaker: Speaker, backend: str) -> None:
        """Enumerate installed voices and send the list to the player."""
        try:
            if isinstance(speaker, NaturalVoiceSpeaker):
                natural_voices = list(speaker.available_voices)
            else:
                natural_voices = discover_natural_voices(self._config.speech)
        except Exception:
            logger.exception("speaker.voice.discovery_failed")
            natural_voices = []

        options = build_voice_options(natural_voices, self._config.speech)
        if isinstance(speaker, NaturalVoiceSpeaker):
            selected_key = natural_voice_key(speaker.voice.package_path, speaker.voice.name)
        elif backend == "supertonic":
            selected_key = supertonic_voice_key(self._config.supertonic_voice)
        else:
            raise TypeError(f"Unsupported SelectSpeak backend: {backend}")

        with self._lock:
            self._options = {option.key: option for option in options}
            self._selected_key = selected_key
        self._player.set_voice_options(options, selected_key)

    # -- selection ---------------------------------------------------------

    def select(self, key: str) -> None:
        """Switch to the chosen voice, loading or installing it as needed."""
        with self._lock:
            if self._closed:
                return
            option = self._options.get(key)
            if option is None:
                return
            if self._switching or key == self._selected_key:
                return
            current_key = self._selected_key

        if option.backend == "supertonic" and self._install_required(option.supertonic_voice):
            self._request_install(option, current_key)
            return

        activity = BACKEND_LOADING
        with self._lock:
            self._switching = True
            self._activity = activity
        self._on_stop_playback()

        def show_activity() -> None:
            self._player.set_voice_selection(option.key, option.short_label, activity=activity)
            self._player.show_backend_loading(activity)

        # stop() queues an idle playback update. Queue this after it so the
        # loading state remains visible instead of being immediately hidden.
        self._player.call_soon(show_activity)
        worker = threading.Thread(
            target=self._load,
            args=(current_key, option),
            name=f"VoiceSelection-{option.backend}",
        )
        with self._lock:
            if self._closed:
                self._switching = False
                self._activity = ""
                return
            self._worker = worker
            worker.start()

    def _load(self, current_key: str, option: VoiceOption) -> None:
        try:
            created = False
            with self._lock:
                speaker = self._speakers.get(option.backend)
                config = self._config
            selected_config = replace(
                config,
                speech_backend=option.backend,
                preferred_voice_match=(
                    option.key if option.backend == "natural" else config.preferred_voice_match
                ),
                supertonic_voice=(
                    option.supertonic_voice
                    if option.backend == "supertonic"
                    else config.supertonic_voice
                ),
            )
            if option.backend == "natural" and isinstance(speaker, NaturalVoiceSpeaker):
                speaker.select_voice(option.package_path, option.sdk_voice_name)
            elif speaker is None or option.backend == "supertonic":
                speaker = create_speaker(selected_config, self._debug_callback)
                created = True

            actual_backend = speaker_backend(speaker)
            if actual_backend != option.backend:
                if created:
                    speaker.close()
                raise RuntimeError(
                    f"{option.label} is unavailable; SelectSpeak kept the current voice instead."
                )

            with self._lock:
                closed = self._closed
                replaced_speaker = self._speakers.get(option.backend)
                if not closed:
                    self._speakers[option.backend] = speaker
                    self._current_backend = option.backend
                    self._selected_key = option.key
                    self._config = selected_config
            if closed:
                if created:
                    speaker.close()
                return
            if replaced_speaker is not None and replaced_speaker is not speaker:
                replaced_speaker.close()

            self._on_activated(option.backend, option.key, selected_config)

            def show_ready() -> None:
                self._player.set_voice_selection(option.key, option.short_label)
                self._player.show_backend_ready(option.short_label)

            self._player.call_soon(show_ready)
            logger.info(
                "speaker.voice.changed backend=%s key=%s label=%s",
                option.backend,
                option.key,
                option.label,
            )
        except Exception as error:
            logger.exception(
                "speaker.voice.change_failed backend=%s key=%s",
                option.backend,
                option.key,
            )
            with self._lock:
                closed = self._closed
            if not closed:
                self._revert_to(current_key)
                self._player.call_soon(
                    lambda message=str(error): self._player.show_backend_error(message)
                )
        finally:
            with self._lock:
                self._switching = False
                self._activity = ""
                self._worker = None

    # -- the optional Supertonic component ---------------------------------

    def _install_required(self, voice: str) -> bool:
        try:
            return not supertonic_is_ready(voice)
        except Exception:
            logger.exception("supertonic.installation_state_failed")
            return True

    def _request_install(self, option: VoiceOption, current_key: str) -> None:
        if not confirm_supertonic_install():
            self._revert_to(current_key)
            return
        with self._lock:
            if self._switching:
                return
            self._switching = True
            self._activity = BACKEND_INSTALLING
        self._on_stop_playback()
        self._player.call_soon(
            lambda: self._player.set_voice_selection(
                option.key,
                option.short_label,
                activity=BACKEND_INSTALLING,
            )
        )
        self._player.call_soon(lambda: self._player.show_backend_loading(BACKEND_INSTALLING))
        worker = threading.Thread(
            target=self._launch_setup,
            args=(current_key,),
            name="SupertonicSetup",
        )
        with self._lock:
            if self._closed:
                self._switching = False
                self._activity = ""
                return
            self._worker = worker
            worker.start()

    def _launch_setup(self, current_key: str) -> None:
        try:
            launch_supertonic_installer()
        except Exception as error:
            logger.exception("supertonic.setup.launch_failed")
            with self._lock:
                closed = self._closed
                self._switching = False
                self._activity = ""
                self._worker = None
            if not closed:
                self._revert_to(current_key)
                self._player.call_soon(
                    lambda message=str(error): self._player.show_backend_error(message)
                )
            return
        logger.info("supertonic.setup.launched")
        # Setup replaces this installation, so the running application stands
        # down and setup restarts it.
        with self._lock:
            if not self._closed:
                self._player.call_soon(self._on_shutdown_requested)
            self._worker = None

    def _revert_to(self, key: str) -> None:
        """Put the picker back on the voice that is still in use."""
        with self._lock:
            option = self._options.get(key)
        if option is None:
            return
        self._player.call_soon(lambda: self._player.set_voice_selection(option.key, option.short_label))
