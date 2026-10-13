"""ragdesk CLI: index | ask | chat"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ragdesk")
    sub = p.add_subparsers(dest="cmd", required=True)
    ix = sub.add_parser("index", help="build the search index from a folder of docs")
    ix.add_argument("docs", nargs="?")
    ask = sub.add_parser("ask", help="ask one question")
    ask.add_argument("question")
    sub.add_parser("chat", help="interactive questions")
    a = p.parse_args(argv)

    from ragdesk.service import assistant, build_index

    if a.cmd == "index":
        index = build_index(a.docs)
        print(
            f"indexed {len(index.chunks)} chunks from "
            f"{len({c.source for c in index.chunks})} documents"
        )
        return 0
    questions = [a.question] if a.cmd == "ask" else iter(lambda: input("? ").strip(), "")
    for q in questions:
        ans = assistant().ask(q)
        print(ans.answer)
        for c in ans.citations:
            print(f"  [{c.n}] {Path(c.source).name} > {c.section}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
