"""Settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # auto: use the Anthropic API when ANTHROPIC_API_KEY and RAGDESK_MODEL are set, else extractive
    provider: str = field(default_factory=lambda: _env("RAGDESK_PROVIDER", "auto"))
    model: str = field(default_factory=lambda: _env("RAGDESK_MODEL", ""))
    index_path: Path = field(default_factory=lambda: Path(_env("RAGDESK_INDEX", "data/index.pkl")))
    docs_path: Path = field(default_factory=lambda: Path(_env("RAGDESK_DOCS", "samples/handbook")))
    top_k: int = field(default_factory=lambda: int(_env("RAGDESK_TOP_K", "5")))


def get_settings() -> Settings:
    return Settings()
