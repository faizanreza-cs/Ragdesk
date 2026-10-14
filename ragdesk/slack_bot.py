"""Slack bot (Socket Mode): mention the bot or DM it and it answers with sources.

pip install 'ragdesk[slack]'
export SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-...
python -m ragdesk.slack_bot
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ragdesk.answer import Answer
from ragdesk.service import assistant


def _esc(s: str) -> str:
    """Slack control characters: doc text must not become <!channel> pings or masked links."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_answer(ans: Answer) -> str:
    """Slack mrkdwn: the answer, then a compact source list."""
    if ans.declined:
        return f":mag: {_esc(ans.answer)}"
    sources = "\n".join(
        f"[{c.n}] {_esc(Path(c.source).name)} › {_esc(c.section)}" for c in ans.citations
    )
    return f"{_esc(ans.answer)}\n\n*Sources*\n{sources}"


def main() -> None:  # pragma: no cover - needs Slack credentials
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    app = App(token=os.environ["SLACK_BOT_TOKEN"])

    def _reply(event: dict, say) -> None:  # type: ignore[no-untyped-def]
        text = re.sub(r"<@[A-Z0-9]+>", "", event.get("text", "")).strip()
        if text:
            say(text=format_answer(assistant().ask(text)), thread_ts=event.get("ts"))

    app.event("app_mention")(_reply)

    @app.event("message")
    def _dm(event: dict, say) -> None:  # type: ignore[no-untyped-def]
        if event.get("channel_type") == "im" and not event.get("bot_id"):
            _reply(event, say)

    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


if __name__ == "__main__":
    main()
