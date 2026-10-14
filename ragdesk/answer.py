"""Answer questions from retrieved chunks, with citations, and decline when unsupported."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from ragdesk.config import Settings, get_settings
from ragdesk.index import Hit, Index, tokenize

DECLINE = (
    "I couldn't find that in the company documents. Try rephrasing, or ask the team that owns "
    "the policy."
)

SYSTEM = """\
You answer employee questions using ONLY the numbered sources provided.
- Cite every factual sentence with its source number in square brackets, e.g. [2].
- If the sources do not contain the answer, reply with exactly: NOT_FOUND
- Quote numbers, limits and deadlines exactly as written. Do not add outside knowledge.
- Be brief: two to four sentences. No preamble.
"""


@dataclass
class Citation:
    n: int
    source: str
    section: str
    chunk_id: str
    snippet: str


@dataclass
class Answer:
    question: str
    answer: str
    declined: bool
    citations: list[Citation] = field(default_factory=list)
    generator: str = ""
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Generator(Protocol):
    name: str

    def generate(self, question: str, hits: list[Hit]) -> str: ...


def _sources_block(hits: list[Hit]) -> str:
    return "\n\n".join(
        f"[{n}] ({h.chunk.title} > {h.chunk.section})\n{h.chunk.text}"
        for n, h in enumerate(hits, start=1)
    )


class AnthropicGenerator:
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        import anthropic

        if not settings.model:
            raise ValueError("RAGDESK_MODEL must be set to an Anthropic model id")
        self.model = settings.model
        self.client = anthropic.Anthropic()

    def generate(self, question: str, hits: list[Hit]) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"<sources>\n{_sources_block(hits)}\n</sources>\n\n"
                    f"Question: {question}",
                }
            ],
        )
        if resp.stop_reason == "refusal":
            return "NOT_FOUND"
        return "".join(b.text for b in resp.content if b.type == "text").strip()


class OpenAIGenerator:  # pragma: no cover - needs network and a key
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        from openai import OpenAI

        self.model = os.environ.get("RAGDESK_OPENAI_MODEL") or settings.model
        self.client = OpenAI()

    def generate(self, question: str, hits: list[Hit]) -> str:
        r = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": f"<sources>\n{_sources_block(hits)}\n"
                    f"</sources>\n\nQuestion: {question}",
                },
            ],
        )
        return (r.choices[0].message.content or "").strip()


class ExtractiveGenerator:
    """Offline fallback: return the best-matching sentences verbatim, with citations."""

    name = "extractive"

    def __init__(self, idf: Callable[[str], float] | None = None) -> None:
        self.idf = idf or (lambda _t: 1.0)

    def generate(self, question: str, hits: list[Hit]) -> str:
        q = set(tokenize(question))
        w = {t: self.idf(t) for t in q}
        total = sum(w.values()) or 1.0
        scored: list[tuple[float, int, str]] = []
        for n, h in enumerate(hits[:3], start=1):
            for sent in re.split(r"(?<=[.!?])\s+", h.chunk.text.replace("\n", " ")):
                words = set(tokenize(sent))
                if not words:
                    continue
                overlap = sum(w[t] for t in q & words) / total
                bonus = 0.15 if re.search(r"\d", sent) else 0.0  # policies live in the numbers
                scored.append((overlap + bonus - 0.05 * (n - 1), n, sent.strip()))
        ranked = sorted(scored, key=lambda s: -s[0])
        if not ranked or ranked[0][0] < 0.25:
            return "NOT_FOUND"
        # keep a second sentence only if it is nearly as relevant as the first
        top = [ranked[0]] + [s for s in ranked[1:2] if s[0] >= 0.75 * ranked[0][0]]
        return " ".join(f"{s} [{n}]" for _, n, s in top)


def get_generator(name: str | None = None, settings: Settings | None = None) -> Generator:
    s = settings or get_settings()
    name = (name or s.provider).lower()
    if name == "auto":
        name = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") and s.model else "extractive"
    if name == "anthropic":
        return AnthropicGenerator(s)
    if name == "openai":
        return OpenAIGenerator(s)
    if name in {"extractive", "mock"}:
        return ExtractiveGenerator()
    raise ValueError(f"unknown provider {name!r} (auto | anthropic | openai | extractive)")


class Assistant:
    def __init__(
        self, index: Index, generator: Generator | None = None, settings: Settings | None = None
    ) -> None:
        self.index = index
        self.settings = settings or get_settings()
        self.generator = generator or get_generator(settings=self.settings)
        if isinstance(self.generator, ExtractiveGenerator):
            self.generator.idf = index.idf

    def ask(self, question: str) -> Answer:
        t0 = time.perf_counter()
        hits = self.index.search(question, k=self.settings.top_k)
        relevant = hits
        # guardrail 1: nothing relevant enough was retrieved -> don't ask the model to guess
        if not relevant or max(h.lexical_overlap for h in relevant) < 0.3:
            return Answer(
                question,
                DECLINE,
                True,
                generator=self.generator.name,
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        text = self.generator.generate(question, relevant)
        cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text)})
        valid = [n for n in cited if 1 <= n <= len(relevant)]
        # guardrail 2: the model said it can't answer, or cited nothing / a source it wasn't given
        declined = text.strip() == "NOT_FOUND" or not cited or len(valid) != len(cited)
        citations = (
            []
            if declined
            else [
                Citation(
                    n,
                    relevant[n - 1].chunk.source,
                    relevant[n - 1].chunk.section,
                    relevant[n - 1].chunk.id,
                    relevant[n - 1].chunk.text[:240],
                )
                for n in valid
            ]
        )
        return Answer(
            question,
            DECLINE if declined else text,
            declined,
            citations,
            self.generator.name,
            int((time.perf_counter() - t0) * 1000),
        )
