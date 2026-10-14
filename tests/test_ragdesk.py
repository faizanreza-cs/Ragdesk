from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ragdesk.answer import DECLINE, Assistant, ExtractiveGenerator
from ragdesk.config import Settings
from ragdesk.index import Index, tokenize
from ragdesk.ingest import chunk_markdown, load_corpus, read_text
from ragdesk.slack_bot import format_answer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def index() -> Index:
    return Index.build(load_corpus(ROOT / "samples" / "handbook"))


@pytest.fixture(scope="module")
def bot(index) -> Assistant:
    return Assistant(index, ExtractiveGenerator(), Settings())


def test_chunks_keep_sections():
    md = "# Title\n\n## Alpha\n\none\n\n## Beta\n\ntwo"
    chunks = chunk_markdown(md, "x.md")
    assert [(c.section, c.text) for c in chunks] == [("Alpha", "one"), ("Beta", "two")]
    assert chunks[0].id == "x.md#0" and chunks[0].title == "Title"


def test_long_sections_split_with_overlap():
    md = "# T\n\n" + "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(10))
    chunks = chunk_markdown(md, "y.md", max_chars=500, overlap=100)
    assert len(chunks) > 2
    assert all(len(c.text) <= 500 + 100 + 300 for c in chunks)


def test_html_ingest(tmp_path):
    p = tmp_path / "p.html"
    p.write_text("<html><nav>menu</nav><h1>Doc</h1><h2>Leave</h2><p>Ten days.</p></html>")
    text = read_text(p)
    assert "## Leave" in text and "menu" not in text


def test_tokenize_normalises_401k():
    assert "401k" in tokenize("401(k) plan") and "401k" in tokenize("401k")


def test_hybrid_search_ranks_right_doc(index):
    hits = index.search("hotel cap in London", k=3)
    assert Path(hits[0].chunk.source).name == "03-expenses.md"
    assert hits[0].score <= 1.0 and hits[0].bm25_rank == 1


def test_answer_is_cited(bot):
    ans = bot.ask("How much is the home office stipend?")
    assert not ans.declined and "$500" in ans.answer
    assert ans.citations and ans.citations[0].source.endswith("03-expenses.md")
    assert "[1]" in ans.answer


def test_declines_off_topic(bot):
    ans = bot.ask("Who won the football World Cup in 2022?")
    assert ans.declined and ans.answer == DECLINE and not ans.citations


class Liar:
    """A generator that cites a source that doesn't exist."""

    name = "liar"

    def __init__(self, text: str = "Everyone gets 99 days off [7].") -> None:
        self.text = text

    def generate(self, question, hits):
        return self.text


@pytest.mark.parametrize(
    "text",
    [
        "Everyone gets 99 days off [7].",
        "PTO is 20 days [1]. Everyone also gets 99 bonus days off [7].",  # one real, one fake
        "Everyone gets 99 days off.",
    ],
)
def test_uncited_or_bad_citations_are_declined(index, text):
    ans = Assistant(index, Liar(text), Settings(top_k=3)).ask("How many PTO days do we get?")
    assert ans.declined


class NotFound:
    name = "nf"

    def generate(self, question, hits):
        return "NOT_FOUND"


def test_model_not_found_is_declined(index):
    assert Assistant(index, NotFound(), Settings()).ask("What is the 401k match?").declined


def test_index_roundtrip(index, tmp_path):
    p = index.save(tmp_path / "i.pkl")
    again = Index.load(p)
    assert len(again.chunks) == len(index.chunks)
    assert again.search("sick days")[0].chunk.id == index.search("sick days")[0].chunk.id


def test_slack_format(bot):
    text = format_answer(bot.ask("What are the core hours?"))
    assert "*Sources*" in text and "05-remote-work.md" in text
    ans = bot.ask("What are the core hours?")
    ans.answer = "Hi <!channel> see <https://x|here>"
    assert "<!channel>" not in format_answer(ans) and "&lt;!channel&gt;" in format_answer(ans)


def test_ingest_survives_real_folders(tmp_path):
    (tmp_path / "hr").mkdir()
    (tmp_path / "it").mkdir()
    (tmp_path / "hr" / "policy.md").write_text("# HR\n\nLeave rules.")
    (tmp_path / "it" / "policy.md").write_text("# IT\n\nLaptop rules.")
    (tmp_path / "old.txt").write_bytes("caf\xe9 menu".encode("latin-1"))  # not UTF-8
    (tmp_path / "notes.md").mkdir()  # a folder with a document suffix
    (tmp_path / "big.md").write_text("x. " * 10_000)  # one paragraph, no blank lines
    chunks = load_corpus(tmp_path)
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)) and "hr/policy.md#0" in ids
    assert all(not c.source.startswith("/") for c in chunks)
    assert max(len(c.text) for c in chunks) <= 900 + 150 + 1


def test_api(tmp_path, monkeypatch):
    monkeypatch.setenv("RAGDESK_INDEX", str(tmp_path / "idx.pkl"))
    monkeypatch.setenv("RAGDESK_DOCS", str(ROOT / "samples" / "handbook"))
    monkeypatch.setenv("RAGDESK_PROVIDER", "extractive")
    from ragdesk import service
    from ragdesk.api import app

    service.assistant.cache_clear()
    c = TestClient(app)
    assert c.get("/health").json()["chunks"] > 10
    r = c.post("/ask", json={"question": "What is the daily meal allowance?"}).json()
    assert "$75" in r["answer"] and r["citations"]
    assert c.get("/widget.js").status_code == 200
    assert "ragdesk" in c.get("/").text
    assert c.post("/reindex").status_code == 403  # disabled without RAGDESK_ADMIN_TOKEN
    monkeypatch.setenv("RAGDESK_ADMIN_TOKEN", "s3cret")
    assert c.post("/reindex", headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert c.post("/reindex", headers={"X-Admin-Token": "s3cret"}).json()["chunks"] > 10
    service.assistant.cache_clear()


def test_eval_thresholds():
    import sys

    sys.path.insert(0, str(ROOT))
    from evals.run_eval import run

    s = run("extractive")["summary"]
    assert s["hit_at_k"] >= 0.9 and s["answer_accuracy"] >= 0.85 and s["false_declines"] == 0
