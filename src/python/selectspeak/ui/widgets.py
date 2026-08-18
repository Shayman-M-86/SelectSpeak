"""Fluent-styled Tk controls used by the player chrome.

Tk's stock widgets draw a Motif-era bevel and keep a pressed border after focus,
so the player builds its buttons from labels with explicit hover/pressed fills.
That is also how it gets the Fluent behaviour Tk has no notion of: an arrow
cursor over controls, a 1px stroke, and a text/icon pair on one baseline.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from .theme import Palette


class FluentButton(tk.Frame):
    """A button drawn as a filled surface with a stroke, text and optional icon.

    ``accent`` renders the Fluent accent (primary) style; otherwise the button
    uses the standard subtle fill.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        palette: Palette,
        text: str,
        command: Callable[[], None],
        text_font: tuple[str, int] | tuple[str, int, str],
        icon: str = "",
        icon_font: tuple[str, int] | None = None,
        accent: bool = False,
        danger: bool = False,
        padx: int = 12,
        pady: int = 6,
    ) -> None:
        super().__init__(
            parent,
            bg=palette.control_border,
            padx=1,
            pady=1,
            highlightthickness=0,
            bd=0,
        )
        self._palette = palette
        self._command = command
        self._accent = accent
        self._danger = danger
        self._enabled = True
        self._hovering = False

        self._surface = tk.Frame(self, bg=self._fill(), padx=padx, pady=pady, highlightthickness=0, bd=0)
        self._surface.pack(fill="both", expand=True)

        self._icon_label: tk.Label | None = None
        if icon and icon_font is not None:
            self._icon_label = tk.Label(
                self._surface,
                text=icon,
                bg=self._fill(),
                fg=self._foreground(),
                font=icon_font,
            )
            self._icon_label.pack(side="left", padx=(0, 8 if text else 0))

        self._text_label = tk.Label(
            self._surface,
            text=text,
            bg=self._fill(),
            fg=self._foreground(),
            font=text_font,
        )
        if text:
            self._text_label.pack(side="left")

        for widget in self._parts():
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<ButtonRelease-1>", self._on_release)

    def _parts(self) -> tuple[tk.Misc, ...]:
        parts: list[tk.Misc] = [self._surface, self._text_label]
        if self._icon_label is not None:
            parts.append(self._icon_label)
        return tuple(parts)

    def _fill(self, *, hover: bool = False, pressed: bool = False) -> str:
        palette = self._palette
        if not self._enabled:
            return palette.subtle_background
        if self._accent:
            if pressed:
                return palette.accent_pressed
            return palette.accent_hover if hover else palette.accent
        if pressed:
            return palette.control_background_pressed
        return palette.control_background_hover if hover else palette.control_background

    def _foreground(self) -> str:
        palette = self._palette
        if not self._enabled:
            return palette.text_disabled
        if self._accent:
            return palette.text_on_accent
        if self._danger:
            return palette.danger
        return palette.text_primary

    def _repaint(self, *, hover: bool = False, pressed: bool = False) -> None:
        fill = self._fill(hover=hover, pressed=pressed)
        foreground = self._foreground()
        self._surface.config(bg=fill)
        self._text_label.config(bg=fill, fg=foreground)
        if self._icon_label is not None:
            self._icon_label.config(bg=fill, fg=foreground)
        self.config(bg=self._palette.control_border if self._enabled else self._palette.subtle_background)

    def _on_enter(self, _event: tk.Event) -> None:
        if not self._enabled:
            return
        self._hovering = True
        self._repaint(hover=True)

    def _on_leave(self, _event: tk.Event) -> None:
        self._hovering = False
        self._repaint()

    def _on_press(self, _event: tk.Event) -> None:
        if not self._enabled:
            return
        self._repaint(pressed=True)

    def _on_release(self, event: tk.Event) -> None:
        if not self._enabled:
            return
        self._repaint(hover=self._hovering)
        # Only fire when released inside the control, matching Win32 buttons.
        widget = event.widget
        inside = (
            0 <= event.x < widget.winfo_width() and 0 <= event.y < widget.winfo_height()
        )
        if inside:
            self._command()

    def configure_state(self, *, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self._repaint(hover=self._hovering and enabled)

    def set_text(self, text: str) -> None:
        self._text_label.config(text=text)
        if text and not self._text_label.winfo_ismapped():
            self._text_label.pack(side="left")

    def set_icon(self, icon: str) -> None:
        if self._icon_label is not None:
            self._icon_label.config(text=icon)

    def set_command(self, command: Callable[[], None]) -> None:
        self._command = command

    def set_style(self, *, accent: bool | None = None, danger: bool | None = None) -> None:
        if accent is not None:
            self._accent = accent
        if danger is not None:
            self._danger = danger
        self._repaint(hover=self._hovering)


class CaptionButton(tk.Label):
    """A titlebar button using Windows caption metrics and hover fills.

    Close uses the Windows close-red hover; minimise uses the subtle fill.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        palette: Palette,
        icon: str,
        command: Callable[[], None],
        icon_font: tuple[str, int],
        close: bool = False,
    ) -> None:
        super().__init__(
            parent,
            text=icon,
            bg=palette.background,
            fg=palette.text_secondary,
            font=icon_font,
            width=4,
            padx=0,
            pady=4,
        )
        self._palette = palette
        self._command = command
        self._close = close
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _on_enter(self, _event: tk.Event) -> None:
        if self._close:
            # Windows keeps the close glyph white on its red hover fill.
            self.config(bg="#c42b1c", fg="#ffffff")
        else:
            self.config(bg=self._palette.control_background_hover, fg=self._palette.text_primary)

    def _on_leave(self, _event: tk.Event) -> None:
        self.config(bg=self._palette.background, fg=self._palette.text_secondary)

    def _on_press(self, _event: tk.Event) -> None:
        if self._close:
            self.config(bg="#b02b1f", fg="#ffffff")
        else:
            self.config(bg=self._palette.control_background_pressed)

    def _on_release(self, event: tk.Event) -> None:
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self._on_enter(event) if inside else self._on_leave(event)
        if inside:
            self._command()


class SubtleButton(tk.Label):
    """A borderless text button for the status-bar toggles.

    Fluent's "subtle" style: no fill or stroke at rest, a light fill on hover.
    The active state is carried by colour and weight rather than a border.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        palette: Palette,
        text: str,
        command: Callable[[], None],
        font: tuple[str, int] | tuple[str, int, str],
    ) -> None:
        super().__init__(
            parent,
            text=text,
            bg=palette.background,
            fg=palette.text_secondary,
            font=font,
            padx=8,
            pady=4,
        )
        self._palette = palette
        self._command = command
        self._enabled = True
        self._foreground = palette.text_secondary
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _on_enter(self, _event: tk.Event) -> None:
        if self._enabled:
            self.config(bg=self._palette.control_background_hover)

    def _on_leave(self, _event: tk.Event) -> None:
        self.config(bg=self._palette.background)

    def _on_press(self, _event: tk.Event) -> None:
        if self._enabled:
            self.config(bg=self._palette.control_background_pressed)

    def _on_release(self, event: tk.Event) -> None:
        if not self._enabled:
            return
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self.config(bg=self._palette.control_background_hover if inside else self._palette.background)
        if inside:
            self._command()

    def set_active(self, active: bool, *, font: tuple[str, int] | tuple[str, int, str]) -> None:
        self._foreground = self._palette.accent if active else self._palette.text_secondary
        self.config(fg=self._foreground, font=font)

    def configure_state(self, *, enabled: bool) -> None:
        self._enabled = enabled
        self.config(fg=self._foreground if enabled else self._palette.text_disabled)
