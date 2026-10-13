"""Retrieval and answer-quality evaluation on evals/questions.yaml.

Retrieval:  hit@k (right document in the top k) and MRR.
Answers:    correctness (expected facts present), citation precision (cited chunks come from
            the expected document), and abstention (declines exactly the unanswerable ones).

python evals/run_eval.py                       # offline extractive generator
python evals/run_eval.py --generator anthropic # needs ANTHROPIC_API_KEY + RAGDESK_MODEL
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ragdesk.answer import Assistant, get_generator  # noqa: E402
from ragdesk.config import Settings  # noqa: E402
from ragdesk.index import Index  # noqa: E402
from ragdesk.ingest import load_corpus  # noqa: E402


def run(generator: str, k: int = 5) -> dict:
    cases = yaml.safe_load((ROOT / "evals" / "questions.yaml").read_text())
    settings = Settings(top_k=k)
    index = Index.build(load_corpus(ROOT / "samples" / "handbook"))
    bot = Assistant(index, get_generator(generator, settings), settings)
    rows = []
    for c in cases:
        answerable = c.get("answerable", True)
        hits = index.search(c["q"], k=k)
        rank = next(
            (i + 1 for i, h in enumerate(hits) if Path(h.chunk.source).name == c.get("source")),
            None,
        )
        ans = bot.ask(c["q"])
        correct = (
            not ans.declined and all(e.lower() in ans.answer.lower() for e in c["expect"])
            if answerable
            else ans.declined
        )
        cites = [Path(x.source).name for x in ans.citations]
        rows.append(
            {
                "q": c["q"],
                "answerable": answerable,
                "rank": rank,
                "declined": ans.declined,
                "correct": correct,
                "citation_precision": (sum(s == c["source"] for s in cites) / len(cites))
                if cites and answerable
                else None,
                "answer": ans.answer,
            }
        )
    ans_rows = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    cp = [r["citation_precision"] for r in ans_rows if r["citation_precision"] is not None]
    summary = {
        "generator": generator,
        "questions": len(rows),
        "k": k,
        "hit_at_k": round(sum(r["rank"] is not None for r in ans_rows) / len(ans_rows), 3),
        "mrr": round(sum(1 / r["rank"] for r in ans_rows if r["rank"]) / len(ans_rows), 3),
        "answer_accuracy": round(sum(r["correct"] for r in ans_rows) / len(ans_rows), 3),
        "citation_precision": round(sum(cp) / len(cp), 3) if cp else None,
        "abstention_accuracy": round(sum(r["correct"] for r in unans) / len(unans), 3),
        "false_declines": sum(r["declined"] for r in ans_rows),
    }
    return {"summary": summary, "rows": rows}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--generator", default="extractive")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--min-hit-rate", type=float, default=0.0)
    a = p.parse_args()
    out = run(a.generator, a.k)
    for r in out["rows"]:
        mark = "ok  " if r["correct"] else "MISS"
        print(f"{mark} rank={r['rank']!s:<4} {r['q'][:60]:<60} -> {r['answer'][:70]}")
    print(json.dumps(out["summary"], indent=2))
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / f"eval_{a.generator}.json").write_text(json.dumps(out, indent=2))
    return 0 if out["summary"]["hit_at_k"] >= a.min_hit_rate else 1


if __name__ == "__main__":
    sys.exit(main())
