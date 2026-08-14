from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import sys
import sysconfig
import zipfile
from collections import deque
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

LAYER_VERSION = "1"
MODEL_REVISION = "724fb5abbf5502583fb520898d45929e62f02c0b"
EXCLUDED_DISTRIBUTIONS = {
    "cffi",
    "hf-xet",
    "pycparser",
    "soundfile",
}
REQUIRED_LAYER_PATHS = (
    Path("supertonic/__init__.py"),
    Path("numpy/__init__.py"),
    Path("onnxruntime/__init__.py"),
)
REQUIRED_MODEL_PATHS = (
    Path("onnx/tts.json"),
    Path("onnx/unicode_indexer.json"),
    Path("onnx/duration_predictor.onnx"),
    Path("onnx/text_encoder.onnx"),
    Path("onnx/vector_estimator.onnx"),
    Path("onnx/vocoder.onnx"),
    Path("voice_styles/F4.json"),
)


def dependency_closure(root_name: str) -> dict[str, importlib.metadata.Distribution]:
    resolved: dict[str, importlib.metadata.Distribution] = {}
    pending = deque([root_name])
    while pending:
        requested = pending.popleft()
        canonical = canonicalize_name(requested)
        if canonical in resolved or canonical in EXCLUDED_DISTRIBUTIONS:
            continue
        distribution = importlib.metadata.distribution(requested)
        resolved[canonical] = distribution
        for expression in distribution.requires or ():
            requirement = Requirement(expression)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            dependency = canonicalize_name(requirement.name)
            if dependency not in EXCLUDED_DISTRIBUTIONS:
                pending.append(requirement.name)
    return resolved


def stage_dependency_layer(destination: Path) -> dict[str, str]:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    distributions = dependency_closure("supertonic")

    for distribution in distributions.values():
        for relative in distribution.files or ():
            source = Path(str(distribution.locate_file(relative))).resolve()
            try:
                target_relative = source.relative_to(site_packages)
            except ValueError:
                # Console entry points outside site-packages are not runtime dependencies.
                continue
            if not source.is_file() or "__pycache__" in target_relative.parts:
                continue
            if source.suffix.casefold() in {".pyc", ".pyo"}:
                continue
            target = destination / target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    missing = [str(path) for path in REQUIRED_LAYER_PATHS if not (destination / path).is_file()]
    if missing:
        raise RuntimeError(f"The staged Supertonic layer is incomplete: {missing}")

    versions = {
        distribution.metadata["Name"] or name: distribution.version
        for name, distribution in sorted(distributions.items())
    }
    manifest = {
        "schema_version": 1,
        "layer_version": LAYER_VERSION,
        "python_tag": f"cp{sys.version_info.major}{sys.version_info.minor}",
        "platform_tag": "win_amd64",
        "packages": versions,
        "excluded_optional_packages": sorted(EXCLUDED_DISTRIBUTIONS),
    }
    (destination / "supertonic-layer.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return versions


def stage_model(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    missing = [str(path) for path in REQUIRED_MODEL_PATHS if not (source / path).is_file()]
    if missing:
        raise RuntimeError(f"The Supertonic model source is incomplete: {missing}")

    for directory in ("onnx", "voice_styles"):
        shutil.copytree(source / directory, destination / directory)
    for filename in ("LICENSE", "README.md", "config.json"):
        candidate = source / filename
        if candidate.is_file():
            shutil.copy2(candidate, destination / filename)
    manifest = {
        "schema_version": 1,
        "model": "supertonic-3",
        "revision": MODEL_REVISION,
    }
    (destination / "supertonic-model.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def create_archive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                information = zipfile.ZipInfo(
                    path.relative_to(source).as_posix(),
                    date_time=(2020, 1, 1, 0, 0, 0),
                )
                information.compress_type = zipfile.ZIP_DEFLATED
                information.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                with path.open("rb") as input_file, archive.open(information, "w") as output_file:
                    shutil.copyfileobj(input_file, output_file, length=1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build optional Supertonic release payloads.")
    parser.add_argument("--layer-output", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument(
        "--model-source",
        type=Path,
        default=Path.home() / ".cache" / "supertonic3",
    )
    parser.add_argument("--staging-root", type=Path, required=True)
    arguments = parser.parse_args()

    layer_stage = arguments.staging_root / "dependencies"
    model_stage = arguments.staging_root / "model"
    versions = stage_dependency_layer(layer_stage)
    create_archive(layer_stage, arguments.layer_output)
    stage_model(arguments.model_source.resolve(), model_stage)
    create_archive(model_stage, arguments.model_output)
    print(
        json.dumps(
            {
                "layer": str(arguments.layer_output.resolve()),
                "model": str(arguments.model_output.resolve()),
                "packages": versions,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
