"""Deterministic offline embeddings for pipeline validation.

This is deliberately a reproducible baseline, not a claim of state-of-the-art
Chinese semantic retrieval. It hashes normalized character n-grams into a
fixed-size vector so indexing and querying use exactly the same transformation.
"""

from __future__ import annotations

import hashlib
import math
import re


SPACE_RE = re.compile(r"\s+")


class CharacterNgramEmbedding:
    """Chroma-compatible, dependency-free character n-gram embedder."""

    def __init__(self, dimensions: int = 768, min_n: int = 1, max_n: int = 3):
        if dimensions <= 0:
            raise ValueError("dimensions必须大于0")
        if not 1 <= min_n <= max_n:
            raise ValueError("必须满足1 <= min_n <= max_n")
        self.dimensions = dimensions
        self.min_n = min_n
        self.max_n = max_n

    @staticmethod
    def name() -> str:
        return "local-character-ngram-v1"

    def _embed_one(self, text: str) -> list[float]:
        normalized = SPACE_RE.sub("", text).lower()
        vector = [0.0] * self.dimensions
        for n in range(self.min_n, self.max_n + 1):
            for start in range(max(0, len(normalized) - n + 1)):
                token = normalized[start:start + n].encode("utf-8")
                digest = hashlib.blake2b(token, digest_size=8).digest()
                value = int.from_bytes(digest, "big")
                index = value % self.dimensions
                sign = 1.0 if value & 1 else -1.0
                vector[index] += sign
        norm = math.sqrt(sum(item * item for item in vector))
        return [item / norm for item in vector] if norm else vector

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in input]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self(texts)

    def embed_query(self, input: str | list[str]) -> list[float] | list[list[float]]:
        if isinstance(input, str):
            return self._embed_one(input)
        return self(input)

