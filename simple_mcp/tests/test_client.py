"""The Slack client's tool loop and routing, with a scripted Claude and the real TERMINUS server in memory."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from fastmcp import Client

from terminal_mcp import server

pytest.importorskip("slack_sdk")
_spec = importlib.util.spec_from_file_location(
    "mcp_slack_client", Path(__file__).resolve().parents[1] / "client" / "mcp_slack_client.py"
)
slack_client = importlib.util.module_from_spec(_spec)
sys.modules["mcp_slack_client"] = slack_client
_spec.loader.exec_module(slack_client)


def _message(*blocks) -> Message:
    return Message(
        id="msg",
        type="message",
        role="assistant",
        model="scripted",
        content=list(blocks),
        stop_reason="tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


class ScriptedClaude:
    """Replays answers in order and records every request."""

    def __init__(self, *answers: Message):
        self.answers = list(answers)
        self.requests: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return self.answers.pop(0)


@pytest.fixture
def bot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "cwds", {server.LOCAL: str(tmp_path)})
    monkeypatch.setattr(server, "settings", server.Settings())
    instance = slack_client.SlackMCPClient.__new__(slack_client.SlackMCPClient)
    instance.model = "scripted"
    instance.db = slack_client.ChatDatabase(str(tmp_path / "chat.db"))
    instance.bot_user_id = "UBOT"
    instance._tasks = set()
    return instance


async def test_a_tool_call_runs_on_the_server_and_its_output_reaches_the_model(bot, tmp_path: Path):
    (tmp_path / "hello.txt").write_text("hi there")
    bot.claude = ScriptedClaude(
        _message(
            ToolUseBlock(type="tool_use", id="t1", name="run_terminal_command", input={"command": "cat hello.txt"})
        ),
        _message(TextBlock(type="text", text="The file says *hi there*.")),
    )
    async with Client(server.mcp) as mcp:
        bot.mcp = mcp
        bot.tools = [{"name": t.name, "description": t.description, "input_schema": {}} for t in await mcp.list_tools()]
        session = bot.db.create_session_id("C1", "111.1")
        bot.db.upsert_session(session, "C1", "U1", "111.1")
        answer = await bot.process_with_context("what's in hello.txt?", session)

    assert answer == "The file says *hi there*."
    second = bot.claude.requests[1]["messages"]
    tool_result = second[-1]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and tool_result["is_error"] is False
    assert "hi there" in tool_result["content"]
    assert [m["role"] for m in bot.db.get_session_history(session)] == ["user", "assistant"]


async def test_history_is_replayed_as_alternating_turns(bot):
    session = bot.db.create_session_id("C1", "222.2")
    bot.db.upsert_session(session, "C1", "U1", "222.2")
    bot.db.save_message(session, "user", "first")
    bot.db.save_message(session, "user", "second")  # e.g. an earlier answer failed
    bot.db.save_message(session, "assistant", "reply")
    bot.claude = ScriptedClaude(_message(TextBlock(type="text", text="ok")))
    bot.mcp, bot.tools = None, []
    await bot.process_with_context("third", session)
    sent = bot.claude.requests[0]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"] == "first\n\nsecond"


def test_thread_replies_are_answered_only_in_the_bots_threads_and_mentions_only_once(bot):
    session = bot.db.create_session_id("C1", "333.3")
    bot.db.upsert_session(session, "C1", "U1", "333.3")
    assert bot._wants_message({"channel": "C1", "thread_ts": "333.3", "text": "and now?"})
    assert not bot._wants_message({"channel": "C1", "thread_ts": "999.9", "text": "someone else's thread"})
    assert not bot._wants_message({"channel": "C1", "thread_ts": "333.3", "text": "<@UBOT> again"})  # app_mention
    assert bot._wants_message({"channel": "D1", "channel_type": "im", "text": "hi"})
