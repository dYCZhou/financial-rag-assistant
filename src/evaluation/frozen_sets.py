"""Canonical hashing and manifest helpers for frozen evaluation sets."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


def canonical_frozen_bytes(path: Path) -> bytes:
    """Return UTF-8 bytes with platform line endings normalized to LF."""
    text = path.read_bytes().decode("utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def frozen_sha256(path: Path) -> str:
    """Hash the canonical semantic bytes of a frozen question CSV."""
    return hashlib.sha256(canonical_frozen_bytes(path)).hexdigest()


def manifest_document_ids(manifest_path: Path, *, accepted_status: str) -> list[str]:
    """Return document IDs in manifest order for the requested status."""
    with manifest_path.open(encoding="utf-8-sig", newline="") as stream:
        return [
            row["document_id"]
            for row in csv.DictReader(stream)
            if row.get("parse_status") == accepted_status
        ]
