from pathlib import Path

from selectspeak.speech.model_installation import supertonic_model_is_installed


def test_supertonic_model_requires_engine_files_and_selected_voice(tmp_path: Path) -> None:
    required = (
        "onnx/tts.json",
        "onnx/unicode_indexer.json",
        "onnx/duration_predictor.onnx",
        "onnx/text_encoder.onnx",
        "onnx/vector_estimator.onnx",
        "onnx/vocoder.onnx",
        "voice_styles/F4.json",
    )
    for relative in required:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    assert supertonic_model_is_installed("F4", tmp_path)
    assert not supertonic_model_is_installed("M1", tmp_path)


def test_incomplete_supertonic_download_is_not_reported_as_installed(tmp_path: Path) -> None:
    partial_model = tmp_path / "onnx/duration_predictor.onnx"
    partial_model.parent.mkdir(parents=True)
    partial_model.touch()

    assert not supertonic_model_is_installed("F4", tmp_path)
