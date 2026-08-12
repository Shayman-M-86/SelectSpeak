from pathlib import Path


def repository_runtime_path(*parts: str) -> Path:
    """Resolve a development/runtime asset from the repository root."""
    repository_root = Path(__file__).resolve().parents[2]
    return repository_root.joinpath(".runtime", *parts)
