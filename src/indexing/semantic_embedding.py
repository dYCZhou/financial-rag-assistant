"""Chinese semantic embeddings backed by a frozen SentenceTransformer model."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
@lru_cache(maxsize=2)
def _load_model(model_path: str):
    from sentence_transformers import SentenceTransformer

    if model_path == MODEL_ID:
        return SentenceTransformer(model_path, revision=MODEL_REVISION)
    return SentenceTransformer(model_path)


class BgeSmallZhEmbedding:
    """Chroma-compatible BGE Chinese semantic embedding adapter."""

    dimensions = 512

    def __init__(self, model_path: str | Path = MODEL_ID):
        self.model_path = str(model_path)

    @staticmethod
    def name() -> str:
        return "bge-small-zh-v1.5"

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = _load_model(self.model_path).encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, query: str) -> list[float]:
        if not query.strip():
            raise ValueError("查询问题不能为空")
        return self._encode([query])[0]
