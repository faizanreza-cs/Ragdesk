"""Load documents and split them into heading-aware chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader


@dataclass
class Chunk:
    id: str
    source: str
    title: str  # document title
    section: str  # nearest heading
    text: str


def read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".html", ".htm"}:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        # keep headings as markdown so sections survive
        for level in range(1, 4):
            for h in soup.find_all(f"h{level}"):
                h.replace_with(f"\n{'#' * level} {h.get_text(strip=True)}\n")
        return soup.get_text("\n")
    if suffix == ".pdf":
        return "\n\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
    raise ValueError(f"unsupported file type: {suffix}")


def chunk_markdown(text: str, source: str, max_chars: int = 900, overlap: int = 150) -> list[Chunk]:
    """Split on headings first, then pack paragraphs up to max_chars with overlap."""
    title = next((m.group(1).strip() for m in re.finditer(r"^#\s+(.+)$", text, re.M)), source)
    sections: list[tuple[str, str]] = []
    current = title
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^#{1,3}\s+(.+)$", line)
        if m:
            if "".join(buf).strip():
                sections.append((current, "\n".join(buf).strip()))
            current, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((current, "\n".join(buf).strip()))

    chunks: list[Chunk] = []
    for section, body in sections:
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        # hard-split paragraphs longer than a chunk (PDF text often has no blank lines)
        paras = [p[i : i + max_chars] for p in paras for i in range(0, len(p), max_chars)]
        piece = ""
        for p in paras:
            if piece and len(piece) + len(p) > max_chars:
                chunks.append(Chunk("", source, title, section, piece))
                piece = piece[-overlap:] + "\n" + p
            else:
                piece = f"{piece}\n{p}" if piece else p
        if piece:
            chunks.append(Chunk("", source, title, section, piece))
    for i, c in enumerate(chunks):
        c.id = f"{source}#{i}"
    return chunks


def load_corpus(folder: str | Path) -> list[Chunk]:
    folder = Path(folder)
    out: list[Chunk] = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".html", ".htm", ".pdf"}:
            # relative path: unique across subfolders, and no server paths in answers
            out += chunk_markdown(read_text(path), path.relative_to(folder).as_posix())
    return out
