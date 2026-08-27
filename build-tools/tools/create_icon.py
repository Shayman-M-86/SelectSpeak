"""Build the Windows application icon from the project logo.

Everything that shows an icon - the frozen executable, the WinUI player, the
installer, its uninstall entry, and the Start menu and desktop shortcuts -
reads the .ico this writes, so the logo only needs converting in one place.
"""

import sys
from pathlib import Path

from PIL import Image

# Windows picks the nearest size and scales the rest, so ship the shell's
# standard set rather than letting it resample one large image badly.
ICON_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

LOGO_PATH = Path(__file__).resolve().parents[2] / "logo" / "SelectSpeak-logo.png"


def _square(image: Image.Image) -> Image.Image:
    """Pad the logo to a square so the icon scales without distortion."""
    if image.width == image.height:
        return image
    side = max(image.width, image.height)
    padded = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    padded.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return padded


def main() -> None:
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)

    if not LOGO_PATH.is_file():
        raise SystemExit(f"The project logo is missing: {LOGO_PATH}")

    # Convert to RGBA before squaring so a palette or greyscale source keeps
    # its transparency instead of picking up a solid background.
    with Image.open(LOGO_PATH) as source:
        logo = _square(source.convert("RGBA"))

    logo.save(output, format="ICO", sizes=ICON_SIZES)


if __name__ == "__main__":
    main()
