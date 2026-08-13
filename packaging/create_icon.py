import sys
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    drawing = ImageDraw.Draw(image)
    drawing.ellipse([16, 16, 240, 240], fill="#89b4fa")
    drawing.polygon(
        [(80, 88), (80, 168), (120, 168), (176, 208), (176, 48), (120, 88)],
        fill="#1e1e2e",
    )
    image.save(output, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])


if __name__ == "__main__":
    main()
