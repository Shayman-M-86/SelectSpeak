"""Choosing and loading the speech engine behind the selected voice.

Switching voice is the one action here that cannot happen inline: a Natural
Voice has to be initialised, and Supertonic may need its model loaded or its
whole dependency layer installed first. So it runs on its own thread, holds its
own "a switch is in progress" state, and the rest of the application asks
whether it is busy rather than tracking it.

The controller owns the speakers it builds. The application layer holds the one
that is current and does not create them itself.
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
from ..speech.feature_installer import launch_supertonic_installer
from ..speech.model_installation import supertonic_model_is_installed
from ..speech.optional_dependencies import supertonic_dependencies_are_installed
from ..speech.voices import VoiceOption, build_voice_options, natural_voice_key
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
    return "supertonic" if "supertonic" in name else "sapi"


class VoiceController:
    """Own voice selection, engine loading and the Supertonic install handoff.

    ``on_activated`` receives the speaker and config for a voice that finished
    loading; the application layer makes it current and persists the settings.
    ``on_stop_playback`` is called before a switch, because the engine that is
    speaking is about to be replaced.
    """

    def __init__(
        self,
        config: AppConfig,
        player: Player,
        *,
        word_callback: Callable[[str, int, int], None],
        debug_callback: SpeechDebugCallback,
        on_activated: Callable[[Speaker, str, str, AppConfig], None],
        on_stop_playback: Callable[[], None],
        on_shutdown_requested: Callable[[], None],
    ) -> None:
        self._config = config
        self._player = player
        self._word_callback = word_callback
        self._debug_callback = debug_callback
        self._on_activated = on_activated
        self._on_stop_playback = on_stop_playback
        self._on_shutdown_requested = on_shutdown_requested

        self._lock = threading.RLock()
        self._speakers: dict[str, Speaker] = {}
        self._options: dict[str, VoiceOption] = {}
        self._selected_key = ""
        self._switching = False
        self._activity = ""
        self._closed = False

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
    def speakers(self) -> tuple[Speaker, ...]:
        with self._lock:
            return tuple(self._speakers.values())

    def close(self) -> None:
        """Stop accepting switches; a load in flight discards its result."""
        with self._lock:
            self._closed = True

    # -- startup -----------------------------------------------------------

    def adopt(self, speaker: Speaker, backend: str, config: AppConfig) -> None:
        """Take ownership of the speaker the application started with."""
        with self._lock:
            self._config = config
            self._speakers[backend] = speaker
        self.publish_options(speaker, backend)

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
            selected_key = natural_voice_key(speaker.voice.package_path)
        elif backend == "supertonic":
            selected_key = "supertonic"
        else:
            selected_key = "sapi"

        with self._lock:
            self._options = {option.key: option for option in options}
            self._selected_key = selected_key
        self._player.set_voice_options(options, selected_key)

    # -- selection ---------------------------------------------------------

    def select(self, key: str) -> None:
        """Switch to the chosen voice, loading or installing it as needed."""
        with self._lock:
            option = self._options.get(key)
            if option is None:
                return
            if self._switching or key == self._selected_key:
                return
            current_key = self._selected_key

        if option.backend == "supertonic" and self._install_required():
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
        threading.Thread(
            target=self._load,
            args=(current_key, option),
            daemon=True,
            name=f"VoiceSelection-{option.backend}",
        ).start()

    def _load(self, current_key: str, option: VoiceOption) -> None:
        try:
            with self._lock:
                speaker = self._speakers.get(option.backend)
                config = self._config
            selected_config = replace(
                config,
                speech_backend=option.backend,
                preferred_voice_match=(
                    option.package_path if option.backend == "natural" else config.preferred_voice_match
                ),
            )
            if option.backend == "natural" and isinstance(speaker, NaturalVoiceSpeaker):
                speaker.select_voice(option.package_path)
            elif speaker is None:
                speaker = create_speaker(selected_config, self._word_callback, self._debug_callback)

            with self._lock:
                if self._closed:
                    return
                self._speakers[option.backend] = speaker
                self._selected_key = option.key
                self._config = selected_config

            self._on_activated(speaker, option.backend, option.key, selected_config)

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
            self._revert_to(current_key)
            self._player.call_soon(lambda message=str(error): self._player.show_backend_error(message))
        finally:
            with self._lock:
                self._switching = False
                self._activity = ""

    # -- the optional Supertonic component ---------------------------------

    def _install_required(self) -> bool:
        try:
            return not (
                supertonic_dependencies_are_installed()
                and supertonic_model_is_installed(self._config.supertonic_voice)
            )
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
        threading.Thread(
            target=self._launch_setup,
            args=(current_key,),
            daemon=True,
            name="SupertonicSetup",
        ).start()

    def _launch_setup(self, current_key: str) -> None:
        try:
            launch_supertonic_installer()
        except Exception as error:
            logger.exception("supertonic.setup.launch_failed")
            self._revert_to(current_key)
            self._player.call_soon(lambda message=str(error): self._player.show_backend_error(message))
            with self._lock:
                self._switching = False
                self._activity = ""
            return
        logger.info("supertonic.setup.launched")
        # Setup replaces this installation, so the running application stands
        # down and setup restarts it.
        self._player.call_soon(self._on_shutdown_requested)

    def _revert_to(self, key: str) -> None:
        """Put the picker back on the voice that is still in use."""
        with self._lock:
            option = self._options.get(key)
        if option is None:
            return
        self._player.call_soon(lambda: self._player.set_voice_selection(option.key, option.short_label))
