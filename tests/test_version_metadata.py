from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_release_version_metadata_matches_project_version() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    numeric_version = f"{version}.0"
    version_tuple = tuple(int(part) for part in numeric_version.split("."))

    package_source = _read("src/python/selectspeak/__init__.py")
    assert f'__version__ = "{version}"' in package_source

    manifest = _read("build-tools/app/SelectSpeak.manifest")
    assert f'version="{numeric_version}"' in manifest

    version_info = _read("build-tools/app/version_info.txt")
    tuple_text = f"({', '.join(str(part) for part in version_tuple)})"
    assert f"filevers={tuple_text}" in version_info
    assert f"prodvers={tuple_text}" in version_info
    assert f'StringStruct("FileVersion", "{version}")' in version_info
    assert f'StringStruct("ProductVersion", "{version}")' in version_info

    cmake = _read("src/native/CMakeLists.txt")
    assert f'SET(SELECTSPEAK_VERSION "{version}"' in cmake.upper()

    installer = _read("build-tools/installer/SelectSpeak.iss")
    assert f'#define AppVersion "{version}"' in installer
    assert f'#define AppNumericVersion "{numeric_version}"' in installer


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
