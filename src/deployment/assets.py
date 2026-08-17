"""Download and verify the immutable runtime assets used by the hosted demo."""

from __future__ import annotations

import hashlib
import os
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from src.parsing.parse_report import ROOT


DEFAULT_ASSET_URL = (
    "https://github.com/dYCZhou/financial-rag-assistant/releases/download/"
    "demo-assets-v1/financial-rag-demo-assets-v1.tar.gz"
)
DEFAULT_ASSET_SHA256 = "913b1a9a89e074c4ee9a858000a7db27176c0d2f8518727b06c2e482d81bb6fb"
ASSET_URL_ENV = "DEMO_ASSETS_URL"
ASSET_SHA256_ENV = "DEMO_ASSETS_SHA256"
READY_MARKER = ROOT / ".demo-assets-ready"
REQUIRED_PATHS = (
    ROOT / "chroma_db" / "chroma.sqlite3",
    ROOT / "data" / "chunks",
    ROOT / "data" / "parsed",
)


class DemoAssetError(RuntimeError):
    """Raised when hosted-demo assets cannot be prepared safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assets_ready(root: Path = ROOT) -> bool:
    required = (
        root / "chroma_db" / "chroma.sqlite3",
        root / "data" / "chunks",
        root / "data" / "parsed",
    )
    return (
        all(path.exists() for path in required)
        and len(list((root / "data" / "chunks").glob("*_chunks.jsonl"))) >= 30
        and len(list((root / "data" / "parsed").glob("*_pages.jsonl"))) >= 15
    )


def _safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            if destination not in target.parents and target != destination:
                raise DemoAssetError("运行资产包含不安全路径，已拒绝解压。")
            if member.issym() or member.islnk():
                raise DemoAssetError("运行资产包含链接文件，已拒绝解压。")
        bundle.extractall(destination, members=members)


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "financial-rag-assistant-demo/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            with destination.open("wb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
    except Exception as exc:
        raise DemoAssetError("运行资产下载失败，请稍后刷新页面。") from exc


def ensure_demo_assets(
    *,
    root: Path = ROOT,
    url: str | None = None,
    expected_sha256: str | None = None,
) -> bool:
    """Ensure runtime assets exist; return True only when a download occurred."""
    if assets_ready(root):
        return False

    asset_url = (url or os.getenv(ASSET_URL_ENV, DEFAULT_ASSET_URL)).strip()
    expected = (
        expected_sha256 or os.getenv(ASSET_SHA256_ENV, DEFAULT_ASSET_SHA256)
    ).strip().lower()
    if not expected or len(expected) != 64:
        raise DemoAssetError("部署未配置有效的运行资产SHA-256。")

    root.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="demo-assets-", suffix=".tar.gz", dir=root, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        _download(asset_url, temporary_path)
        actual = sha256_file(temporary_path)
        if actual != expected:
            raise DemoAssetError("运行资产完整性校验失败，已拒绝加载。")
        _safe_extract(temporary_path, root)
        if not assets_ready(root):
            raise DemoAssetError("运行资产不完整，请联系维护者。")
        (root / READY_MARKER.name).write_text(actual + "\n", encoding="utf-8")
        return True
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
