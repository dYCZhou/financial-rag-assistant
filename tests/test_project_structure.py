from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_required_directories_exist() -> None:
    required = [
        "configs",
        "data/raw_pdf",
        "data/manifests",
        "data/parsed",
        "data/chunks",
        "data/evaluation",
        "chroma_db",
        "src/ingestion",
        "src/parsing",
        "src/chunking",
        "src/indexing",
        "src/retrieval",
        "src/generation",
        "src/evaluation",
        "app",
        "reports",
        "logs",
    ]
    assert all((ROOT / path).is_dir() for path in required)
