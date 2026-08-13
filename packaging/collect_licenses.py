from __future__ import annotations

import importlib.metadata
import shutil
import sys
from pathlib import Path

PACKAGES = (
    "certifi",
    "huggingface-hub",
    "numpy",
    "onnxruntime",
    "pillow",
    "pystray",
    "pywin32",
    "supertonic",
)
LICENSE_NAMES = ("license", "copying", "notice")


def main() -> None:
    destination = Path(sys.argv[1])
    destination.mkdir(parents=True, exist_ok=True)
    summary = ["# Bundled Python dependencies", ""]
    for package in PACKAGES:
        distribution = importlib.metadata.distribution(package)
        name = distribution.metadata["Name"] or package
        version = distribution.version
        expressions = distribution.metadata.get_all("License-Expression") or []
        licenses = distribution.metadata.get_all("License") or []
        expression = next(iter([*expressions, *licenses]), None)
        summary.append(f"- {name} {version}: {expression or 'see project metadata/upstream'}")
        copied = 0
        for relative in distribution.files or ():
            if not any(part.casefold().startswith(LICENSE_NAMES) for part in relative.parts):
                continue
            source = Path(str(distribution.locate_file(relative)))
            if not source.is_file():
                continue
            target = destination / f"{name}-{version}" / Path(*relative.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
        if not copied:
            summary.append(f"  - No license text was present in the installed wheel for {name}.")
    (destination / "PYTHON_DEPENDENCIES.md").write_text("\n".join(summary) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
