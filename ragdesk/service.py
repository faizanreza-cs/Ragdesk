"""Build or load the index once and share the assistant across API, CLI and Slack."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ragdesk.answer import Assistant
from ragdesk.config import get_settings
from ragdesk.index import Index
from ragdesk.ingest import load_corpus


def build_index(docs: str | Path | None = None, out: str | Path | None = None) -> Index:
    s = get_settings()
    index = Index.build(load_corpus(docs or s.docs_path))
    index.save(out or s.index_path)
    return index


@lru_cache(maxsize=1)
def assistant() -> Assistant:
    s = get_settings()
    index = Index.load(s.index_path) if s.index_path.exists() else build_index()
    return Assistant(index, settings=s)
