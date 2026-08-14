from pathlib import Path

from ..config.paths import model_dir

_SUPERTONIC_REQUIRED_FILES = (
    Path("onnx/tts.json"),
    Path("onnx/unicode_indexer.json"),
    Path("onnx/duration_predictor.onnx"),
    Path("onnx/text_encoder.onnx"),
    Path("onnx/vector_estimator.onnx"),
    Path("onnx/vocoder.onnx"),
)


def supertonic_model_is_installed(
    voice: str,
    root: Path | None = None,
) -> bool:
    """Return whether the local model and selected voice style are complete."""
    model_root = root or model_dir("supertonic3")
    required = (*_SUPERTONIC_REQUIRED_FILES, Path("voice_styles") / f"{voice}.json")
    return all((model_root / relative).is_file() for relative in required)
