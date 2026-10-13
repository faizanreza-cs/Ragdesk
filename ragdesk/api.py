"""REST API + embeddable widget. Run: uvicorn ragdesk.api:app --reload"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from ragdesk import __version__
from ragdesk.service import assistant, build_index

WIDGET = Path(__file__).resolve().parents[1] / "widget"

app = FastAPI(
    title="ragdesk",
    version=__version__,
    description="Answers from your company docs, with citations.",
)
# the widget is embedded on other sites; restrict origins in production
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["POST", "GET"], allow_headers=["*"]
)


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


@app.get("/health")
def health() -> dict[str, Any]:
    a = assistant()
    return {"status": "ok", "generator": a.generator.name, "chunks": len(a.index.chunks)}


@app.post("/ask")
def ask(q: Question) -> dict[str, Any]:
    return assistant().ask(q.question).to_dict()


@app.post("/reindex")
def reindex() -> dict[str, Any]:
    index = build_index()
    assistant.cache_clear()
    return {"chunks": len(index.chunks)}


@app.get("/widget.js")
def widget_js() -> FileResponse:
    return FileResponse(WIDGET / "ragdesk-widget.js", media_type="application/javascript")


@app.get("/", response_class=HTMLResponse)
def demo() -> str:
    return (WIDGET / "demo.html").read_text()
