"""Build the immutable hosted-demo asset archive and print its SHA-256."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

from src.deployment.assets import assets_ready, sha256_file
from src.parsing.parse_report import ROOT


def package_assets(output: Path, root: Path = ROOT) -> Path:
    if not assets_ready(root):
        raise FileNotFoundError("缺少完整chroma_db、30个Chunk文件或15个页面JSONL")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz", compresslevel=6) as archive:
        archive.add(root / "chroma_db", arcname="chroma_db")
        archive.add(root / "data" / "chunks", arcname="data/chunks")
        archive.add(root / "data" / "parsed", arcname="data/parsed")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "financial-rag-demo-assets-v1.tar.gz",
    )
    args = parser.parse_args()
    output = package_assets(args.output.resolve())
    print(f"asset={output}")
    print(f"bytes={output.stat().st_size}")
    print(f"sha256={sha256_file(output)}")


if __name__ == "__main__":
    main()
