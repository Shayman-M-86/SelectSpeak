import ctypes
import logging
import os
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from queue import Empty, SimpleQueue

from ..speech.debug import SpeechDebugEvent
from ..speech.voices import VoiceOption
from .debug_panel import SpeechDebugPanelModel
from .dwm import apply_native_frame, enable_shadow, top_level_handle
from .hints import backend_loading_message, idle_hint, shortcut_label
from .theme import (
    BODY_SIZE,
    CAPTION_ICON_SIZE,
    CAPTION_SIZE,
    FONT_FAMILY,
    FONT_FAMILY_DISPLAY,
    FONT_FAMILY_FALLBACK,
    ICON_ACCEPT,
    ICON_APP,
    ICON_CHEVRON_DOWN,
    ICON_CLOSE,
    ICON_FAMILY,
    ICON_FAMILY_FALLBACK,
    ICON_KEYBOARD,
    ICON_MINIMIZE,
    ICON_PAUSE,
    ICON_PLAY,
    ICON_REPLAY,
    ICON_SIZE,
    ICON_STOP,
    ICON_WARNING,
    MIN_DEBUG_READING_HEIGHT,
    MIN_IDLE_HEIGHT,
    MIN_READING_HEIGHT,
    MONO_FAMILY,
    MONO_FAMILY_FALLBACK,
    PARAGRAPH_GAP,
    PROGRESS_INTERVAL_MS,
    PROGRESS_THICKNESS,
    PROGRESS_WIDTH,
    STATUS_WRAP_LENGTH,
    SUBTITLE_SIZE,
    WINDOW_WIDTH,
    load_palette,
    resolve_font_family,
)
from .widgets import CaptionButton, FluentButton, SubtleButton
from .window_state import foreground_window_is_fullscreen

logger = logging.getLogger(__name__)

_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TRANSPARENT = 0x00000020
_SWP_REFRESH_FRAME_NO_ACTIVATE = 0x0037
# Fluent overlays are opaque; DWM supplies the depth via shadow, not alpha.
_VISIBLE_ALPHA = 1.0


class PlayerWindow(tk.Tk):
    def __init__(
        self,
        *,
        app_name: str,
        hotkey: str,
        ocr_hotkey: str = "alt+d",
        on_play: Callable[[], None],
        on_read: Callable[[], None],
        on_pause: Callable[[], None],
        on_resume: Callable[[], None],
        on_stop: Callable[[], None],
        on_refresh_voices: Callable[[], None],
        on_select_voice: Callable[[str], None],
        on_toggle_clipboard: Callable[[], None],
        on_toggle_auto_hide: Callable[[], None],
        on_toggle_debug: Callable[[], None],
        on_capture_hotkey: Callable[[], None],
        auto_hide: bool = True,
        speech_backend: str = "windows",
        debug_enabled: bool = False,
    ) -> None:
        super().__init__()
        self._app_name = app_name
        self._hotkey = hotkey
        self._ocr_hotkey = ocr_hotkey
        self._clipboard_mode = False
        self._auto_hide = auto_hide
        self._speech_backend = speech_backend
        self._on_refresh_voices = on_refresh_voices
        self._on_select_voice = on_select_voice
        self._voice_options: tuple[VoiceOption, ...] = ()
        self._selected_voice_key = tk.StringVar(self, "")
        self._debug_enabled = debug_enabled
        self._debug = SpeechDebugPanelModel()
        self._on_play = on_play
        self._on_read = on_read
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._on_stop = on_stop
        self._animation_job: str | None = None
        self._animation_offset = 0
        self._reader_generation = 0
        self._reader_text = ""
        self._callbacks: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self._drag_x = 0
        self._drag_y = 0
        self._user_minimized = False
        self._playback_started_fullscreen = False
        self._soft_hidden = False

        self._palette = load_palette()
        self._init_fonts()

        self.title(app_name)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", _VISIBLE_ALPHA)
        self.configure(bg=self._palette.background)
        self.resizable(False, False)
        self.update_idletasks()
        self._enable_no_activate()
        self._apply_native_frame()

        self.bind("<ButtonPress-1>", self._begin_drag)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Map>", self._on_map)

        palette = self._palette
        # A 1px stroke around the whole surface, as Fluent flyouts have.
        self._border = tk.Frame(self, bg=palette.control_border, highlightthickness=0, bd=0)
        self._border.pack(fill="both", expand=True)
        self._content = tk.Frame(
            self._border,
            bg=palette.background,
            padx=16,
            pady=12,
            highlightthickness=0,
            bd=0,
        )
        self._content.pack(fill="both", expand=True, padx=1, pady=1)
        self._build_title_row(self._content)
        self._build_status(self._content)
        self._build_reader(self._content)
        self._build_controls(
            self._content,
            on_toggle_clipboard=on_toggle_clipboard,
            on_toggle_auto_hide=on_toggle_auto_hide,
            on_toggle_debug=on_toggle_debug,
            on_capture_hotkey=on_capture_hotkey,
        )
        self.update_idletasks()
        width, height = self._required_size(MIN_IDLE_HEIGHT)
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(
            f"{width}x{height}+{max(0, screen_width - width - 20)}+{max(0, screen_height - height - 60)}"
        )
        self.after(20, self._drain_callbacks)
        self.withdraw()
        logger.info(
            "player.created app_name=%s hotkey=%s initial_mode=%s "
            "auto_hide=%s width=%s height=%s requested_width=%s "
            "requested_height=%s scaling=%s theme=%s",
            app_name,
            hotkey,
            "auto",
            auto_hide,
            width,
            height,
            self._content.winfo_reqwidth(),
            self._content.winfo_reqheight(),
            round(float(self.tk.call("tk", "scaling")), 3),
            "dark" if self._palette.dark else "light",
        )

    def _init_fonts(self) -> None:
        """Resolve the Segoe families once, then align Tk's own named fonts.

        Menus and dialogs read the named fonts, so setting them here is what
        makes the voice menu match the rest of the window.
        """
        body = resolve_font_family(self, FONT_FAMILY, FONT_FAMILY_FALLBACK)
        display = resolve_font_family(self, FONT_FAMILY_DISPLAY, body)
        icons = resolve_font_family(self, ICON_FAMILY, ICON_FAMILY_FALLBACK)
        mono = resolve_font_family(self, MONO_FAMILY, MONO_FAMILY_FALLBACK)

        self._font_body = (body, BODY_SIZE)
        self._font_caption = (body, CAPTION_SIZE)
        self._font_caption_strong = (body, CAPTION_SIZE, "bold")
        self._font_title = (display, SUBTITLE_SIZE, "bold")
        self._font_icon = (icons, ICON_SIZE)
        self._font_caption_icon = (icons, CAPTION_ICON_SIZE)
        self._font_mono = (mono, CAPTION_SIZE)

        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            try:
                tkfont.nametofont(name).configure(family=body, size=BODY_SIZE)
            except tk.TclError:
                logger.debug("player.font.unavailable name=%s", name)
        logger.debug("player.fonts.resolved body=%s display=%s icons=%s", body, display, icons)

    def _apply_native_frame(self) -> None:
        """Ask DWM for rounded corners and a shadow on the frameless window."""
        try:
            handle = top_level_handle(self.winfo_id())
            apply_native_frame(
                handle,
                dark=self._palette.dark,
                border_colour=self._palette.control_border,
            )
            enable_shadow(handle)
        except Exception:
            logger.exception("player.native_frame.failed")

    def call_soon(self, callback: Callable[[], None]) -> None:
        self._callbacks.put(callback)
        logger.debug(
            "player.callback.queued callback=%s",
            getattr(callback, "__name__", type(callback).__name__),
        )

    def show(self) -> None:
        logger.info("player.show")
        if self._soft_hidden:
            self._set_click_through(False)
            self.attributes("-alpha", _VISIBLE_ALPHA)
            self._soft_hidden = False
        self.deiconify()
        self.lift()

    def hide(self) -> None:
        if self.state() == "withdrawn":
            logger.debug("player.hide.ignored_already_hidden")
            return
        logger.info("player.hidden")
        if self._soft_hidden:
            self._set_click_through(False)
            self.attributes("-alpha", _VISIBLE_ALPHA)
            self._soft_hidden = False
        self.withdraw()

    def _soft_hide(self) -> None:
        """Hide visually without unmapping a window over a fullscreen app."""
        if self.state() == "withdrawn" or self._soft_hidden:
            return
        logger.info("player.hidden mode=transparent_fullscreen")
        self._set_click_through(True)
        self.attributes("-alpha", 0.0)
        self._soft_hidden = True

    def _set_click_through(self, enabled: bool) -> None:
        if os.name != "nt":
            return
        user32 = ctypes.windll.user32
        client_handle = self.winfo_id()
        window_handle = user32.GetParent(client_handle) or client_handle
        style = user32.GetWindowLongPtrW(window_handle, _GWL_EXSTYLE)
        updated = style | _WS_EX_NOACTIVATE
        if enabled:
            updated |= _WS_EX_TRANSPARENT
        else:
            updated &= ~_WS_EX_TRANSPARENT
        if updated != style:
            user32.SetWindowLongPtrW(window_handle, _GWL_EXSTYLE, updated)
            user32.SetWindowPos(window_handle, 0, 0, 0, 0, _SWP_REFRESH_FRAME_NO_ACTIVATE)

    def _enable_no_activate(self) -> None:
        if os.name != "nt":
            logger.debug("player.no_activate.unavailable")
            return
        try:
            user32 = ctypes.windll.user32
            client_handle = self.winfo_id()
            window_handle = user32.GetParent(client_handle) or client_handle
            extended_style = user32.GetWindowLongPtrW(
                window_handle,
                _GWL_EXSTYLE,
            )
            ctypes.set_last_error(0)
            previous_style = user32.SetWindowLongPtrW(
                window_handle,
                _GWL_EXSTYLE,
                extended_style | _WS_EX_NOACTIVATE,
            )
            if previous_style == 0 and ctypes.get_last_error() != 0:
                raise ctypes.WinError(ctypes.get_last_error())
            user32.SetWindowPos(
                window_handle,
                0,
                0,
                0,
                0,
                _SWP_REFRESH_FRAME_NO_ACTIVATE,
            )
            logger.info("player.no_activate.enabled window_handle=%s", window_handle)
        except Exception:
            logger.exception("player.no_activate.failed")

    def set_hotkey(self, hotkey: str) -> None:
        logger.info("player.hotkey.updated hotkey=%s", hotkey)
        self._hotkey = hotkey
        self._hotkey_button.config(text=self._shortcut_label(hotkey))

    def show_hotkey_error(self, message: str) -> None:
        """Report a shortcut that would not bind, where the status line shows it."""
        logger.warning("player.hotkey.rejected message=%s", message)
        self._set_status(message, self._palette.danger, ICON_WARNING)

    def set_ocr_hotkey(self, hotkey: str) -> None:
        logger.info("player.ocr_hotkey.updated hotkey=%s", hotkey)
        self._ocr_hotkey = hotkey
        # No button carries this one, but the idle hint names it, so the hint
        # is reissued to pick up the new shortcut.
        self.show_idle_hint()

    def set_clipboard_mode(self, enabled: bool) -> None:
        logger.info("player.capture_mode.updated mode=%s", "clipboard" if enabled else "auto")
        self._clipboard_mode = enabled
        self._clipboard_button.config(text=f"Source: {'Clipboard' if enabled else 'Automatic'}")
        self._clipboard_button.set_active(
            enabled,
            font=self._font_caption_strong if enabled else self._font_caption,
        )
        self.show_idle_hint()

    def set_auto_hide(self, enabled: bool) -> None:
        self._auto_hide = enabled
        self._auto_hide_button.config(text=f"Auto-hide: {'On' if enabled else 'Off'}")
        self._auto_hide_button.set_active(
            enabled,
            font=self._font_caption_strong if enabled else self._font_caption,
        )
        logger.info("player.auto_hide.updated enabled=%s", enabled)

    def set_debug_enabled(self, enabled: bool) -> None:
        self._debug_enabled = enabled
        self._debug_button.config(text=f"Diagnostics: {'On' if enabled else 'Off'}")
        self._debug_button.set_active(
            enabled,
            font=self._font_caption_strong if enabled else self._font_caption,
        )
        if enabled:
            self._debug_frame.pack(fill="x", pady=(0, 10), before=self._control_row)
            self._render_debug_metrics()
            self._apply_chunk_tags()
        else:
            self._debug_frame.pack_forget()
            self._clear_chunk_tags()
        minimum = (
            MIN_DEBUG_READING_HEIGHT
            if enabled and self._reader_frame.winfo_ismapped()
            else MIN_READING_HEIGHT
            if self._reader_frame.winfo_ismapped()
            else MIN_IDLE_HEIGHT
        )
        self._resize(minimum)
        logger.info("player.speech_debug.updated enabled=%s", enabled)

    def update_speech_debug(self, event: SpeechDebugEvent) -> None:
        display_event = self._debug.update(event)
        if not self._debug_enabled:
            return
        self._apply_chunk_tags(event if event.kind == "chunk_playing" else None)
        self._render_debug_metrics(display_event)

    def reset_speech_debug(self) -> None:
        self._debug.reset()
        self._clear_chunk_tags()
        if self._debug_enabled:
            self._render_debug_metrics()

    def set_voice_options(
        self,
        options: tuple[VoiceOption, ...],
        selected_key: str,
    ) -> None:
        self._voice_options = options
        self._voice_menu.delete(0, "end")
        previous_group = ""
        for option in options:
            if option.group != previous_group:
                if previous_group:
                    self._voice_menu.add_separator()
                self._voice_menu.add_command(label=option.group, state="disabled")
                previous_group = option.group
            self._voice_menu.add_radiobutton(
                label=option.label,
                value=option.key,
                variable=self._selected_voice_key,
                command=lambda key=option.key: self._on_select_voice(key),
            )
        selected = next(
            (option for option in options if option.key == selected_key),
            options[0] if options else None,
        )
        if selected is not None:
            self.set_voice_selection(selected.key, selected.short_label)
        else:
            self._voice_button.config(text="Voice unavailable")
            self._voice_button.configure_state(enabled=False)

    def set_voice_selection(
        self,
        key: str,
        label: str,
        *,
        activity: str = "",
    ) -> None:
        busy = bool(activity)
        if activity == "installing":
            button_text = "Installing Supertonic…"
        elif activity:
            button_text = f"Loading {label}…"
        else:
            button_text = f"Voice: {label}  {ICON_CHEVRON_DOWN}"
        self._selected_voice_key.set(key)
        self._voice_button.config(text=button_text)
        self._voice_button.configure_state(enabled=not busy)
        self._voice_button.set_active(
            key == "supertonic" and not busy,
            font=self._font_caption_strong if key == "supertonic" and not busy else self._font_caption,
        )
        self._read_button.configure_state(enabled=not busy)
        self._play_button.configure_state(enabled=not busy and bool(self._reader_text))
        self._resize(MIN_IDLE_HEIGHT)
        logger.info(
            "player.voice.updated voice_key=%s voice_label=%s activity=%s",
            key,
            label,
            activity or "ready",
        )

    def _show_voice_menu(self) -> None:
        self._on_refresh_voices()
        if not self._voice_options:
            return
        try:
            self._voice_menu.tk_popup(
                self._voice_button.winfo_rootx(),
                self._voice_button.winfo_rooty() + self._voice_button.winfo_height(),
            )
        finally:
            self._voice_menu.grab_release()

    def show_backend_error(self, message: str) -> None:
        self._set_status(f"Voice engine unavailable: {message}", self._palette.danger, ICON_WARNING)
        self.show()

    def show_backend_loading(self, activity: str = "loading") -> None:
        self._set_status(backend_loading_message(activity), self._palette.accent, "")
        self.show()

    def show_backend_ready(self, label: str) -> None:
        self._set_status(f"{label} is ready", self._palette.success, ICON_ACCEPT)
        self.show()

    def show_capture_started(self) -> None:
        logger.info("player.hotkey_capture.started")
        self._set_status(
            "Press the keys for your shortcut, or Esc to cancel",
            self._palette.accent,
            ICON_KEYBOARD,
        )
        self._hotkey_button.config(text="Listening…")

    def show_capture_preview(self, hotkey: str) -> None:
        logger.debug("player.hotkey_capture.preview hotkey=%s", hotkey)
        self._set_status(self._shortcut_label(hotkey), self._palette.accent, ICON_KEYBOARD)
        self._hotkey_button.config(text=self._shortcut_label(hotkey))

    def show_capture_complete(self, hotkey: str) -> None:
        logger.info("player.hotkey_capture.completed hotkey=%s", hotkey)
        self.set_hotkey(hotkey)
        self._set_status(
            f"Shortcut set to {self._shortcut_label(hotkey)}",
            self._palette.success,
            ICON_ACCEPT,
        )
        self.after(2000, self.show_idle_hint)

    def show_idle_hint(self) -> None:
        target = "clipboard" if self._clipboard_mode else "selection or clipboard"
        logger.debug("player.idle_hint.shown target=%s hotkey=%s", target, self._hotkey)
        self._set_status(self._idle_hint(), self._palette.text_secondary, "")
        self._hotkey_button.config(text=self._shortcut_label(self._hotkey))

    def set_playback(self, *, speaking: bool, paused: bool = False, text: str = "") -> None:
        logger.info(
            "player.playback.updated speaking=%s paused=%s text_length=%s",
            speaking,
            paused,
            len(text),
        )
        palette = self._palette
        if speaking and not paused:
            self._start_animation()
            if text != self._reader_text or not self._reader_frame.winfo_ismapped():
                self._show_reader(text)
            else:
                self._reader.tag_config(
                    "current",
                    background=palette.highlight_background,
                    foreground=palette.highlight_foreground,
                )
            self._play_button.set_text("Pause")
            self._play_button.set_icon(ICON_PAUSE)
            self._play_button.set_command(self._on_pause)
            self._play_button.configure_state(enabled=True)
            self._stop_button.configure_state(enabled=True)
            self._playback_started_fullscreen = foreground_window_is_fullscreen()
            self.show()
        elif speaking:
            self._stop_animation()
            # Dim the highlight while paused so it reads as inactive.
            self._reader.tag_config(
                "current",
                background=palette.subtle_background,
                foreground=palette.text_primary,
            )
            self._play_button.set_text("Resume")
            self._play_button.set_icon(ICON_PLAY)
            self._play_button.set_command(self._on_resume)
            self._play_button.configure_state(enabled=True)
            self._stop_button.configure_state(enabled=True)
        else:
            self._stop_animation()
            hint = "Finished. Press the shortcut to read again." if text else self._idle_hint()
            self._hide_reader(hint)
            self._play_button.set_text("Replay")
            self._play_button.set_icon(ICON_REPLAY)
            self._play_button.set_command(self._on_play)
            self._play_button.configure_state(enabled=bool(text))
            self._stop_button.configure_state(enabled=False)
            if self._auto_hide:
                hide = self._soft_hide if self._playback_started_fullscreen else self.hide
                self.after_idle(hide)
            self._playback_started_fullscreen = False

    def highlight_word(self, position: int, length: int) -> None:
        generation = self._reader_generation
        logger.debug(
            "player.word_highlight.queued position=%s length=%s reader_generation=%s",
            position,
            length,
            generation,
        )

        def update() -> None:
            if generation != self._reader_generation:
                logger.debug(
                    "player.word_highlight.stale queued_generation=%s current_generation=%s",
                    generation,
                    self._reader_generation,
                )
                return
            self._reader.config(state="normal")
            self._reader.tag_remove("current", "1.0", "end")
            self._reader.tag_add("current", f"1.0+{position}c", f"1.0+{position + length}c")
            self._reader.see(f"1.0+{position}c")
            self._reader.config(state="disabled")
            logger.debug("player.word_highlight.applied position=%s length=%s", position, length)

        self.call_soon(update)

    def _build_title_row(self, parent: tk.Frame) -> None:
        palette = self._palette
        row = tk.Frame(parent, bg=palette.background)
        row.pack(fill="x")
        tk.Label(
            row,
            text=ICON_APP,
            bg=palette.background,
            fg=palette.accent,
            font=self._font_icon,
        ).pack(side="left", padx=(0, 8))
        tk.Label(
            row,
            text=self._app_name,
            bg=palette.background,
            fg=palette.text_primary,
            font=self._font_title,
        ).pack(side="left")

        # Caption buttons sit flush with the window edge, as Windows draws them.
        CaptionButton(
            row,
            palette=palette,
            icon=ICON_CLOSE,
            command=self.hide,
            icon_font=self._font_caption_icon,
            close=True,
        ).pack(side="right", padx=(0, 0))
        CaptionButton(
            row,
            palette=palette,
            icon=ICON_MINIMIZE,
            command=self._minimize,
            icon_font=self._font_caption_icon,
        ).pack(side="right")

        # Indeterminate progress: a bar that travels along an unfilled track
        # while audio plays, the way a Win11 ProgressBar reads.
        self._progress = tk.Canvas(
            row,
            width=PROGRESS_WIDTH,
            height=PROGRESS_THICKNESS,
            bg=palette.subtle_background,
            highlightthickness=0,
            bd=0,
        )
        self._progress_bar = self._progress.create_rectangle(
            0,
            0,
            0,
            PROGRESS_THICKNESS,
            fill=palette.accent,
            width=0,
        )

    def _set_status(self, text: str, colour: str, icon: str) -> None:
        self._status_icon.config(text=icon, fg=colour)
        if icon:
            if not self._status_icon.winfo_ismapped():
                self._status_icon.pack(side="left", padx=(0, 8), anchor="n")
        else:
            self._status_icon.pack_forget()
        self._status.config(text=text, fg=colour)

    def _build_status(self, parent: tk.Frame) -> None:
        palette = self._palette
        self._status_row = tk.Frame(parent, bg=palette.background)
        self._status_row.pack(fill="x", pady=(10, 12))
        self._status_icon = tk.Label(
            self._status_row,
            text="",
            bg=palette.background,
            fg=palette.text_secondary,
            font=self._font_icon,
        )
        self._status = tk.Label(
            self._status_row,
            text=self._idle_hint(),
            bg=palette.background,
            fg=palette.text_secondary,
            font=self._font_body,
            wraplength=STATUS_WRAP_LENGTH,
            justify="left",
            anchor="w",
        )
        self._status.pack(side="left", fill="x", expand=True)

    def _build_reader(self, parent: tk.Frame) -> None:
        palette = self._palette
        # The reader is a Fluent "card": a subtle fill inside a 1px stroke.
        self._reader_frame = tk.Frame(parent, bg=palette.control_border, highlightthickness=0, bd=0)
        self._reader_inner = tk.Frame(self._reader_frame, bg=palette.card_background)
        self._reader_inner.pack(fill="both", expand=True, padx=1, pady=1)
        self._reader = tk.Text(
            self._reader_inner,
            height=9,
            bg=palette.card_background,
            fg=palette.text_primary,
            font=self._font_body,
            wrap="word",
            relief="flat",
            bd=0,
            state="disabled",
            padx=12,
            pady=10,
            cursor="arrow",
            # Every line spacing option inflates some display lines but not
            # others: spacing1/spacing3 pad the first and last line of a
            # paragraph, and spacing2 pads only the lines inside a wrap. Tk
            # paints a tag's background across the whole display line box, so
            # any of them would make the spoken-word highlight change size
            # depending on where the word fell. Keeping all three at zero makes
            # every line box exactly one line tall; the air between paragraphs
            # comes from a blank line instead, which is itself a normal line.
            spacing1=0,
            spacing2=0,
            spacing3=0,
            selectbackground=palette.highlight_background,
            selectforeground=palette.highlight_foreground,
            insertwidth=0,
        )
        self._reader.tag_config(
            "structured_line",
            lmargin1=0,
            lmargin2=0,
        )
        self._reader.tag_config(
            "bullet_line",
            lmargin1=0,
            lmargin2=18,
        )
        # Paragraph air, applied only to the blank lines already present in the
        # text. A line holding no words can be padded freely because no word
        # highlight is ever painted across it.
        self._reader.tag_config(
            "separator",
            spacing3=PARAGRAPH_GAP,
        )
        self._reader.tag_config(
            "current",
            background=palette.highlight_background,
            foreground=palette.highlight_foreground,
        )
        self._reader.pack(fill="both", expand=True)

        self._debug_frame = tk.Frame(parent, bg=palette.control_border, highlightthickness=0, bd=0)
        debug_inner = tk.Frame(self._debug_frame, bg=palette.subtle_background, padx=12, pady=8)
        debug_inner.pack(fill="both", expand=True, padx=1, pady=1)
        self._debug_metrics = tk.Label(
            debug_inner,
            text="Waiting for speech chunks…",
            height=2,
            bg=palette.subtle_background,
            fg=palette.text_secondary,
            font=self._font_mono,
            justify="left",
            anchor="w",
        )
        self._debug_metrics.pack(fill="x")

    def _build_controls(
        self,
        parent: tk.Frame,
        *,
        on_toggle_clipboard: Callable[[], None],
        on_toggle_auto_hide: Callable[[], None],
        on_toggle_debug: Callable[[], None],
        on_capture_hotkey: Callable[[], None],
    ) -> None:
        palette = self._palette
        self._control_row = tk.Frame(parent, bg=palette.background)
        # Reserve the controls at the bottom so an expanding reader or debug
        # panel can never push playback controls outside the client area.
        self._control_row.pack(side="bottom", fill="x")

        # Read is the primary action, so it takes the accent style; the rest
        # are standard buttons, matching how Windows ranks dialog actions.
        self._read_button = FluentButton(
            self._control_row,
            palette=palette,
            text="Read",
            icon=ICON_PLAY,
            icon_font=self._font_icon,
            text_font=self._font_body,
            command=self._on_read,
            accent=True,
        )
        self._read_button.pack(side="left", padx=(0, 8))

        self._play_button = FluentButton(
            self._control_row,
            palette=palette,
            text="Replay",
            icon=ICON_REPLAY,
            icon_font=self._font_icon,
            text_font=self._font_body,
            command=self._on_play,
        )
        self._play_button.pack(side="left", padx=(0, 8))
        # Nothing has been read yet, so replaying and stopping are unavailable.
        self._play_button.configure_state(enabled=False)

        self._stop_button = FluentButton(
            self._control_row,
            palette=palette,
            text="Stop",
            icon=ICON_STOP,
            icon_font=self._font_icon,
            text_font=self._font_body,
            command=self._on_stop,
            danger=True,
        )
        self._stop_button.pack(side="left")
        self._stop_button.configure_state(enabled=False)

        self._voice_menu = tk.Menu(
            self,
            tearoff=False,
            bg=palette.card_background,
            fg=palette.text_primary,
            activebackground=palette.control_background_hover,
            activeforeground=palette.text_primary,
            disabledforeground=palette.text_secondary,
            selectcolor=palette.accent,
            relief="flat",
            bd=0,
            activeborderwidth=0,
            font=self._font_body,
        )

        # Settings sit in their own group, separated from the transport
        # controls by a vertical rule so the two roles do not read as one bar.
        settings = tk.Frame(self._control_row, bg=palette.background)
        settings.pack(side="right")
        tk.Frame(self._control_row, bg=palette.divider, width=1).pack(side="right", fill="y", padx=12, pady=4)

        # Secondary settings read right-to-left in the order they are packed.
        self._hotkey_button = self._subtle_button(
            settings, self._shortcut_label(self._hotkey), on_capture_hotkey
        )
        self._hotkey_button.pack(side="right")
        self._clipboard_button = self._subtle_button(settings, "Source: Automatic", on_toggle_clipboard)
        self._clipboard_button.pack(side="right")
        backend_label = "Supertonic" if self._speech_backend == "supertonic" else "Windows"
        self._voice_button = self._subtle_button(
            settings,
            f"Voice: {backend_label}  {ICON_CHEVRON_DOWN}",
            self._show_voice_menu,
        )
        self._voice_button.set_active(
            self._speech_backend == "supertonic",
            font=self._font_caption_strong if self._speech_backend == "supertonic" else self._font_caption,
        )
        self._voice_button.pack(side="right")
        self._auto_hide_button = self._subtle_button(
            settings,
            f"Auto-hide: {'On' if self._auto_hide else 'Off'}",
            on_toggle_auto_hide,
        )
        self._auto_hide_button.set_active(
            self._auto_hide,
            font=self._font_caption_strong if self._auto_hide else self._font_caption,
        )
        self._auto_hide_button.pack(side="right")
        self._debug_button = self._subtle_button(
            settings,
            f"Diagnostics: {'On' if self._debug_enabled else 'Off'}",
            on_toggle_debug,
        )
        self._debug_button.set_active(
            self._debug_enabled,
            font=self._font_caption_strong if self._debug_enabled else self._font_caption,
        )
        self._debug_button.pack(side="right")

    def _show_reader(self, text: str) -> None:
        logger.debug("player.reader.shown text_length=%s", len(text))
        self._reader_generation += 1
        self._reader_text = text
        self._reader.config(state="normal")
        self._reader.delete("1.0", "end")
        self._reader.insert("1.0", text)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                self._reader.tag_add(
                    "structured_line",
                    f"{line_number}.0",
                    f"{line_number}.end",
                )
                if line.startswith("• "):
                    self._reader.tag_add(
                        "bullet_line",
                        f"{line_number}.0",
                        f"{line_number}.end",
                    )
            else:
                self._reader.tag_add(
                    "separator",
                    f"{line_number}.0",
                    f"{line_number}.end+1c",
                )
        self._reader.tag_remove("current", "1.0", "end")
        self._reader.tag_config(
            "current",
            background=self._palette.highlight_background,
            foreground=self._palette.highlight_foreground,
        )
        self._reader.config(state="disabled")
        if not self._reader_frame.winfo_ismapped():
            self._status_row.pack_forget()
            self._reader_frame.pack(
                fill="both",
                expand=True,
                pady=(10, 12),
                before=self._control_row,
            )
        if self._debug_enabled and not self._debug_frame.winfo_ismapped():
            self._debug_frame.pack(fill="x", pady=(0, 10), before=self._control_row)
        # Measure only after every speaking-mode panel has been inserted.
        self._resize(MIN_DEBUG_READING_HEIGHT if self._debug_enabled else MIN_READING_HEIGHT)
        self._control_row.lift()

    def _clear_chunk_tags(self) -> None:
        self._reader.config(state="normal")
        self._reader.tag_remove("debug_active_chunk", "1.0", "end")
        for index in self._debug.chunks:
            self._reader.tag_remove(f"debug_chunk_{index}", "1.0", "end")
        self._reader.config(state="disabled")

    def _apply_chunk_tags(self, active: SpeechDebugEvent | None = None) -> None:
        if not self._debug_enabled or not self._reader_text:
            return
        palette = self._palette
        chunk_colours = palette.chunk_colours
        self._reader.config(state="normal")
        self._reader.tag_remove("debug_active_chunk", "1.0", "end")
        for index, event in self._debug.chunks.items():
            tag = f"debug_chunk_{index}"
            self._reader.tag_config(
                tag,
                underline=True,
                foreground=chunk_colours[index % len(chunk_colours)],
            )
            self._reader.tag_add(
                tag,
                f"1.0+{event.text_offset}c",
                f"1.0+{event.text_offset + event.text_length}c",
            )
        self._reader.tag_config(
            "debug_active_chunk",
            background=palette.subtle_background,
            foreground=palette.text_primary,
        )
        if active and active.chunk_index is not None:
            self._reader.tag_add(
                "debug_active_chunk",
                f"1.0+{active.text_offset}c",
                f"1.0+{active.text_offset + active.text_length}c",
            )
            self._reader.tag_raise("current")
            self._reader.see(f"1.0+{active.text_offset}c")
        self._reader.config(state="disabled")

    def _render_debug_metrics(self, event: SpeechDebugEvent | None = None) -> None:
        old_required_height = self._debug_frame.winfo_reqheight()
        text, is_underrun = self._debug.metrics(event)
        self._debug_metrics.config(
            text=text,
            fg=self._palette.danger if is_underrun else self._palette.text_secondary,
        )
        self.update_idletasks()
        if (
            self._debug_enabled
            and self._reader_frame.winfo_ismapped()
            and self._debug_frame.winfo_reqheight() != old_required_height
        ):
            self._resize(MIN_DEBUG_READING_HEIGHT)
            self._control_row.lift()

    def _hide_reader(self, hint: str) -> None:
        logger.debug("player.reader.hidden hint=%s", hint)
        self._reader_generation += 1
        self._reader_frame.pack_forget()
        self._debug_frame.pack_forget()
        self._set_status(hint, self._palette.text_secondary, "")
        self._status_row.pack(fill="x", pady=(10, 12), before=self._control_row)
        self._resize(MIN_IDLE_HEIGHT)

    def _start_animation(self) -> None:
        logger.debug("player.animation.started")
        self._stop_animation()
        self._animation_offset = 0
        self._progress.pack(side="left", padx=(12, 0))
        self._animation_tick()

    def _animation_tick(self) -> None:
        # A short bar sweeping left to right, as an indeterminate Win11 bar does.
        span = PROGRESS_WIDTH + PROGRESS_WIDTH // 2
        start = self._animation_offset - PROGRESS_WIDTH // 2
        self._progress.coords(
            self._progress_bar,
            max(0, start),
            0,
            min(PROGRESS_WIDTH, start + PROGRESS_WIDTH // 2),
            PROGRESS_THICKNESS,
        )
        self._animation_offset = (self._animation_offset + 2) % span
        self._animation_job = self.after(PROGRESS_INTERVAL_MS, self._animation_tick)

    def _stop_animation(self) -> None:
        if self._animation_job:
            try:
                self.after_cancel(self._animation_job)
            except tk.TclError:
                pass
            self._animation_job = None
            logger.debug("player.animation.stopped")
        if hasattr(self, "_progress"):
            self._progress.coords(self._progress_bar, 0, 0, 0, PROGRESS_THICKNESS)
            # Remove the track entirely when idle; a bare rail reads as broken.
            self._progress.pack_forget()

    def _shortcut_label(self, hotkey: str) -> str:
        return shortcut_label(hotkey)

    def _idle_hint(self) -> str:
        return idle_hint(self._hotkey, self._ocr_hotkey, clipboard_mode=self._clipboard_mode)

    def _drain_callbacks(self) -> None:
        drained = 0
        try:
            while True:
                self._callbacks.get_nowait()()
                drained += 1
        except Empty:
            pass
        except Exception:
            logger.exception("player.callback.failed callbacks_completed=%s", drained)
        if drained:
            logger.debug("player.callbacks.drained count=%s", drained)
        try:
            self.after(20, self._drain_callbacks)
        except tk.TclError:
            pass

    def _required_size(self, minimum_height: int) -> tuple[int, int]:
        self.update_idletasks()
        width = max(WINDOW_WIDTH, self._content.winfo_reqwidth())
        height = max(minimum_height, self._content.winfo_reqheight())
        return width, height

    def _resize(self, minimum_height: int) -> None:
        current_bottom = self.winfo_y() + self.winfo_height()
        width, height = self._required_size(minimum_height)
        new_y = max(0, current_bottom - height)
        max_x = max(0, self.winfo_screenwidth() - width)
        new_x = min(max(0, self.winfo_x()), max_x)
        self.geometry(f"{width}x{height}+{new_x}+{new_y}")
        logger.debug(
            "player.resized_to_content width=%s height=%s requested_width=%s "
            "requested_height=%s minimum_height=%s scaling=%s",
            width,
            height,
            self._content.winfo_reqwidth(),
            self._content.winfo_reqheight(),
            minimum_height,
            round(float(self.tk.call("tk", "scaling")), 3),
        )

    def _begin_drag(self, event: tk.Event) -> None:
        logger.debug("player.drag.started x=%s y=%s", event.x, event.y)
        self._drag_x = event.x
        self._drag_y = event.y

    def _drag(self, event: tk.Event) -> None:
        self.geometry(f"+{self.winfo_x() + event.x - self._drag_x}+{self.winfo_y() + event.y - self._drag_y}")

    def _minimize(self) -> None:
        logger.info("player.minimized")
        self._user_minimized = True
        self.overrideredirect(False)
        self.iconify()

    def _on_map(self, _event: tk.Event) -> None:
        if self.state() == "normal" and self._user_minimized:
            logger.info("player.restored")
            self._user_minimized = False
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            self.after_idle(self._enable_no_activate)
            self.after_idle(self._apply_native_frame)

    def _subtle_button(self, parent: tk.Frame, text: str, command: Callable[[], None]) -> SubtleButton:
        return SubtleButton(
            parent,
            palette=self._palette,
            text=text,
            command=command,
            font=self._font_caption,
        )
