"""Hybrid retrieval: BM25 (keywords) + vector search, merged with reciprocal-rank fusion.

The offline vector backend is LSA (TF-IDF + truncated SVD). It needs no model download or
API key and captures some synonymy. Swap in API embeddings with RAGDESK_EMBEDDINGS=openai.
"""

from __future__ import annotations

import os
import pickle
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

from ragdesk.ingest import Chunk

_STOP = set(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "for",
        "on",
        "and",
        "or",
        "is",
        "are",
        "be",
        "with",
        "by",
        "at",
        "as",
        "it",
        "this",
        "that",
        "what",
        "how",
        "do",
        "i",
        "my",
        "we",
        "our",
        "you",
        "your",
        "can",
        "does",
    ]
)


def tokenize(text: str) -> list[str]:
    # "401(k)" -> "401k" so it matches how people type it
    text = re.sub(r"(\w)\((\w)\)", r"\1\2", text.lower())
    return [t for t in re.findall(r"[a-z0-9$]+", text) if t not in _STOP]


class LSAEmbedder:
    def __init__(self, dims: int = 64) -> None:
        self.dims = dims
        self.tfidf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        self.svd: TruncatedSVD | None = None

    def fit(self, texts: list[str]) -> np.ndarray:
        x = self.tfidf.fit_transform(texts)
        k = max(2, min(self.dims, x.shape[1] - 1, x.shape[0] - 1))
        self.svd = TruncatedSVD(n_components=k, random_state=0)
        return self._norm(self.svd.fit_transform(x))

    def embed(self, texts: list[str]) -> np.ndarray:
        assert self.svd is not None, "fit first"
        return self._norm(self.svd.transform(self.tfidf.transform(texts)))

    @staticmethod
    def _norm(m: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(n == 0, 1, n)


class OpenAIEmbedder:  # pragma: no cover - needs network and a key
    def __init__(self, model: str | None = None) -> None:
        from openai import OpenAI

        self.client = OpenAI()
        self.model = model or os.environ.get("RAGDESK_EMBED_MODEL", "text-embedding-3-small")

    def fit(self, texts: list[str]) -> np.ndarray:
        return self.embed(texts)

    def embed(self, texts: list[str]) -> np.ndarray:
        data = self.client.embeddings.create(model=self.model, input=texts).data
        m = np.array([d.embedding for d in data])
        return m / np.linalg.norm(m, axis=1, keepdims=True)


def make_embedder() -> Any:
    return OpenAIEmbedder() if os.environ.get("RAGDESK_EMBEDDINGS") == "openai" else LSAEmbedder()


@dataclass
class Hit:
    chunk: Chunk
    score: float  # fused, normalised to 0..1 (1 = ranked first by both retrievers)
    bm25_rank: int | None = None
    vector_rank: int | None = None
    lexical_overlap: float = 0.0  # IDF-weighted share of query terms found in the chunk


@dataclass
class Index:
    chunks: list[Chunk]
    embedder: Any
    vectors: np.ndarray
    bm25: BM25Okapi = field(repr=False)

    @classmethod
    def build(cls, chunks: list[Chunk]) -> Index:
        if not chunks:
            raise ValueError("no chunks to index")
        texts = [f"{c.title}. {c.section}. {c.text}" for c in chunks]
        embedder = make_embedder()
        vectors = embedder.fit(texts)
        return cls(chunks, embedder, vectors, BM25Okapi([tokenize(t) for t in texts]))

    def search(self, query: str, k: int = 5, rrf_k: int = 60, pool: int = 20) -> list[Hit]:
        q_tokens = tokenize(query)
        bm = self.bm25.get_scores(q_tokens) if q_tokens else np.zeros(len(self.chunks))
        vec = self.vectors @ self.embedder.embed([query])[0]
        bm_order = [i for i in np.argsort(-bm)[:pool] if bm[i] > 0]
        vec_order = [i for i in np.argsort(-vec)[:pool] if vec[i] > 0]
        fused: dict[int, float] = {}
        for rank, i in enumerate(bm_order):
            fused[i] = fused.get(i, 0.0) + 1 / (rrf_k + rank + 1)
        for rank, i in enumerate(vec_order):
            fused[i] = fused.get(i, 0.0) + 1 / (rrf_k + rank + 1)
        best = 2 / (rrf_k + 1)
        weights = {t: self.idf(t) for t in q_tokens}
        total_w = sum(weights.values()) or 1.0
        out = []
        for i, s in sorted(fused.items(), key=lambda kv: -kv[1])[:k]:
            words = set(tokenize(self.chunks[i].text + " " + self.chunks[i].section))
            overlap = sum(w for t, w in weights.items() if t in words) / total_w
            out.append(
                Hit(
                    self.chunks[i],
                    round(s / best, 4),
                    bm_order.index(i) + 1 if i in bm_order else None,
                    vec_order.index(i) + 1 if i in vec_order else None,
                    round(overlap, 3),
                )
            )
        return out

    def idf(self, token: str) -> float:
        """Rarity weight: generic words ("company", "policy") count less than specific ones.

        Unseen tokens get the maximum weight, so a question about something the docs never
        mention scores low overlap and is declined.
        """
        idf = self.bm25.idf
        return float(max(idf.get(token, max(idf.values())), 0.05))

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(self, f)
        return path

    @staticmethod
    def load(path: str | Path) -> Index:
        with Path(path).open("rb") as f:
            obj = pickle.load(f)  # only load indexes you built yourself
        if not isinstance(obj, Index):
            raise TypeError("not a ragdesk index")
        return obj
