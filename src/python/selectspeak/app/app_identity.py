"""The Windows application identity shared by both SelectSpeak processes.

SelectSpeak runs as two processes: this backend and the WinUI player. Without
an explicit identity Windows derives one per executable, so the shell treats
them as two unrelated applications - two entries in Task Manager rather than
one expandable group, and separate taskbar buttons.

Setting the same Application User Model ID in both makes the shell treat them
as one application. The player sets the same string on its own side; the two
must stay in step, so change them together.
"""

from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)

# Company.Product, matching AppPublisher and AppName in the installer.
APP_USER_MODEL_ID = "SelectSpeakProject.SelectSpeak"


def apply_app_user_model_id() -> None:
    """Claim the shared shell identity for this process.

    Must run before anything creates a window: the shell reads the identity
    when a window first appears, and a later change does not move a window
    that has already been placed.

    A failure only costs the grouping, so it is logged rather than raised.
    """
    try:
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        result = shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        logger.warning("app_identity.unavailable", exc_info=True)
        return

    if result != 0:
        logger.warning("app_identity.failed hresult=0x%08X", result & 0xFFFFFFFF)
        return
    logger.debug("app_identity.applied id=%s", APP_USER_MODEL_ID)
