import logging
import threading
from collections.abc import Callable

import pystray
from PIL import Image

from ..config.paths import logo_path

logger = logging.getLogger(__name__)


class TrayController:
    def __init__(
        self,
        *,
        app_name: str,
        hotkey: str,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._app_name = app_name
        self._hotkey = hotkey
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon = pystray.Icon(
            app_name,
            self._create_icon(),
            self._title,
            pystray.Menu(
                pystray.MenuItem("Show Player", self._show, default=True),
                pystray.MenuItem(self._hotkey_label, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            ),
        )
        self._thread: threading.Thread | None = None
        logger.info("tray.created app_name=%s hotkey=%s", app_name, hotkey)

    @property
    def _title(self) -> str:
        return f"{self._app_name} — {self._hotkey.upper()}"

    def start(self) -> None:
        logger.info("tray.starting")
        self._thread = threading.Thread(target=self._icon.run, daemon=True, name="SystemTray")
        self._thread.start()
        logger.info("tray.started")

    def stop(self) -> None:
        logger.info("tray.stopping")
        self._icon.stop()
        logger.info("tray.stopped")

    def update_hotkey(self, hotkey: str) -> None:
        logger.info("tray.hotkey.updated previous_hotkey=%s new_hotkey=%s", self._hotkey, hotkey)
        self._hotkey = hotkey
        self._icon.title = self._title
        self._icon.update_menu()

    def _show(self, _icon: object, _item: object) -> None:
        logger.info("tray.show_selected")
        self._on_show()

    def _quit(self, _icon: object, _item: object) -> None:
        logger.info("tray.quit_selected")
        self._on_quit()

    def _hotkey_label(self, _item: object) -> str:
        return f"Hotkey: {self._hotkey.upper()}"

    @staticmethod
    def _create_icon() -> Image.Image:
        """Return the application logo, matching every other SelectSpeak icon."""
        logger.debug("tray.icon.creating")
        path = logo_path()
        with Image.open(path) as source:
            # Load before the file closes, and normalize so a palette or
            # greyscale source keeps its transparency in the tray.
            image = source.convert("RGBA")
        logger.debug("tray.icon.created source=%s", path)
        return image
