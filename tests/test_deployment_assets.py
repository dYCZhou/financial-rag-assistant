import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from src.deployment.assets import DemoAssetError, assets_ready, ensure_demo_assets


def _build_asset_archive(path: Path, *, unsafe: bool = False) -> str:
    with tarfile.open(path, "w:gz") as archive:
        files = {
            "chroma_db/chroma.sqlite3": b"sqlite",
            **{f"data/chunks/doc_{i}_chunks.jsonl": b"{}\n" for i in range(30)},
            **{f"data/parsed/doc_{i}_pages.jsonl": b"{}\n" for i in range(15)},
        }
        if unsafe:
            files["../escape.txt"] = b"unsafe"
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ensure_demo_assets_downloads_verifies_and_extracts(tmp_path: Path) -> None:
    source = tmp_path / "source.tar.gz"
    expected = _build_asset_archive(source)
    target = tmp_path / "runtime"

    downloaded = ensure_demo_assets(
        root=target,
        url=source.as_uri(),
        expected_sha256=expected,
    )

    assert downloaded is True
    assert assets_ready(target)
    assert ensure_demo_assets(root=target, url="bad", expected_sha256=expected) is False


def test_ensure_demo_assets_rejects_wrong_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.tar.gz"
    _build_asset_archive(source)

    with pytest.raises(DemoAssetError, match="完整性"):
        ensure_demo_assets(
            root=tmp_path / "runtime",
            url=source.as_uri(),
            expected_sha256="0" * 64,
        )


def test_ensure_demo_assets_rejects_path_traversal(tmp_path: Path) -> None:
    source = tmp_path / "source.tar.gz"
    expected = _build_asset_archive(source, unsafe=True)

    with pytest.raises(DemoAssetError, match="不安全路径"):
        ensure_demo_assets(
            root=tmp_path / "runtime",
            url=source.as_uri(),
            expected_sha256=expected,
        )
