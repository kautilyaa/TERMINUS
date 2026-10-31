#!/usr/bin/env python3
"""TERMINUS Slack bot: Slack messages → Claude → TERMINUS MCP tools → a threaded reply.

Run the server with an HTTP transport, then point the bot at it:

    terminal-mcp --transport sse --port 8002 --ssh-hosts web1,db1
    python mcp_slack_client.py http://localhost:8002/sse      # or http://localhost:8000/mcp (streamable HTTP)

The bot answers direct messages, @mentions, and replies in threads it is already part of.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import sys
from typing import Any

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastmcp import Client
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
    + ([logging.FileHandler(os.environ["LOG_FILE"])] if os.environ.get("LOG_FILE") else []),
)
logger = logging.getLogger("MCP-Slack-Client")

DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_TURNS = 10
HISTORY_MESSAGES = 10
TOOL_RESULT_MAX = 10_000  # characters of one tool result sent back to the model
SLACK_TEXT_MAX = 39_000  # Slack rejects messages over 40,000 characters
SYSTEM_PROMPT = (
    "You are TERMINUS, a terminal operations assistant in Slack. Use the MCP tools to inspect and manage the "
    "machines they reach: call list_hosts to see which hosts exist, and pass host to act on an SSH host. "
    "Prefer read-only commands; before anything destructive (deleting, restarting, overwriting) say what you will "
    "do and ask for confirmation. Be concise and use Slack formatting (*bold*, `code`, ```blocks```)."
)


class ChatDatabase:
    """SQLite chat history: sessions, messages and tool calls."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.environ.get("DB_PATH", "chat_history.db")
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    thread_ts TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    input_params TEXT,
                    output TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS messages_by_session ON messages(session_id, id);
                CREATE INDEX IF NOT EXISTS sessions_by_thread ON chat_sessions(channel_id, thread_ts);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def create_session_id(channel_id: str, thread_ts: str | None) -> str:
        """One session per Slack thread (everyone in the thread shares its context)."""
        return hashlib.sha256(f"{channel_id}:{thread_ts or 'main'}".encode()).hexdigest()[:32]

    def save_message(self, session_id: str, role: str, content: str, metadata: dict | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata) VALUES (?, ?, ?, ?)",
                (session_id, role, content, json.dumps(metadata) if metadata else None),
            )

    def save_tool_call(self, session_id: str, tool_name: str, input_params: dict, output: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tool_calls (session_id, tool_name, input_params, output, status) VALUES (?, ?, ?, ?, ?)",
                (session_id, tool_name, json.dumps(input_params), output, status),
            )

    def get_session_history(self, session_id: str, limit: int = HISTORY_MESSAGES) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def has_session(self, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
        return row is not None

    def upsert_session(self, session_id: str, channel_id: str, user_id: str, thread_ts: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (session_id, channel_id, user_id, thread_ts) VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, channel_id, user_id, thread_ts),
            )


def history_messages(history: list[dict]) -> list[dict[str, Any]]:
    """Alternating user/assistant turns for the API (merging repeats, starting with the user)."""
    messages: list[dict[str, Any]] = []
    for item in history:
        if messages and messages[-1]["role"] == item["role"]:
            messages[-1]["content"] += "\n\n" + item["content"]
        else:
            messages.append({"role": item["role"], "content": item["content"]})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages


def tool_result_text(result: Any) -> tuple[str, bool]:
    """The text parts of an MCP tool result, clipped, and whether it is an error."""
    parts = [getattr(block, "text", None) or json.dumps(getattr(block, "model_dump", dict)(), default=str)
             for block in (result.content or [])]  # fmt: skip
    text = "\n".join(parts) or "(no output)"
    if len(text) > TOOL_RESULT_MAX:
        text = text[:TOOL_RESULT_MAX] + f"\n… [{len(text) - TOOL_RESULT_MAX} characters cut]"
    return text, bool(result.is_error)


class SlackMCPClient:
    """Slack-integrated MCP client driven by Claude."""

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("CLAUDE_MODEL", DEFAULT_MODEL)
        self.db = ChatDatabase()
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        self.claude = AsyncAnthropic(api_key=api_key)

        slack_token, app_token = os.getenv("SLACK_BOT_TOKEN"), os.getenv("SLACK_APP_TOKEN")
        if not slack_token or not app_token:
            raise ValueError("SLACK_BOT_TOKEN and SLACK_APP_TOKEN are required")
        self.slack_client = AsyncWebClient(token=slack_token)
        self.socket_client = SocketModeClient(app_token=app_token, web_client=self.slack_client)

        self.mcp: Client | None = None
        self.tools: list[dict[str, Any]] = []
        self.bot_user_id: str | None = None
        self._tasks: set[asyncio.Task] = set()

    async def connect_to_mcp_server(self, server_url: str) -> None:
        """Connect once and load the tool list (SSE for URLs ending in /sse, streamable HTTP otherwise)."""
        logger.info("Connecting to MCP server at %s", server_url)
        self.mcp = Client(server_url)
        await self.mcp.__aenter__()
        tools = await self.mcp.list_tools()
        self.tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.model_dump(by_alias=True).get("inputSchema")
                or {"type": "object", "properties": {}},
            }
            for t in tools
        ]
        logger.info("Connected to MCP. Available tools: %s", [t["name"] for t in self.tools])

    async def cleanup(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self.mcp is not None:
            try:
                await self.mcp.__aexit__(None, None, None)
            except Exception as e:  # noqa: BLE001 - best effort on shutdown
                logger.error("MCP cleanup error: %s", e)

    async def process_with_context(self, query: str, session_id: str) -> str:
        """Answer ``query`` with the thread's history, running tool calls until Claude replies with text."""
        history = self.db.get_session_history(session_id)
        self.db.save_message(session_id, "user", query)
        messages = history_messages([*history, {"role": "user", "content": query}])

        for _ in range(MAX_TURNS):
            response = await self.claude.messages.create(
                model=self.model,
                system=SYSTEM_PROMPT,
                tools=self.tools,
                max_tokens=4096,
                messages=messages,
            )
            content = [b.model_dump(exclude_none=True) for b in response.content]
            messages.append({"role": "assistant", "content": content})
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                text = "\n".join(b.text for b in response.content if b.type == "text").strip() or "(No response)"
                self.db.save_message(session_id, "assistant", text)
                return text

            results = await asyncio.gather(*(self._run_tool(session_id, tu) for tu in tool_uses))
            messages.append({"role": "user", "content": list(results)})
        return "I stopped after too many tool calls; try a narrower request."

    async def _run_tool(self, session_id: str, tool_use: Any) -> dict[str, Any]:
        args = tool_use.input or {}
        logger.info("Executing tool %s", tool_use.name)
        try:
            result = await self.mcp.call_tool(tool_use.name, args, raise_on_error=False)
            text, is_error = tool_result_text(result)
        except Exception as e:  # noqa: BLE001 - reported back to the model
            text, is_error = f"Error executing tool '{tool_use.name}': {e}", True
            logger.error(text)
        self.db.save_tool_call(session_id, tool_use.name, args, text, "error" if is_error else "success")
        return {"type": "tool_result", "tool_use_id": tool_use.id, "content": text, "is_error": is_error}

    # ------------------------------------------------------------------ Slack

    async def handle_slack_event(self, client: SocketModeClient, req: SocketModeRequest) -> None:
        if req.type != "events_api":
            return
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        event = req.payload.get("event", {})
        if event.get("bot_id") or event.get("subtype"):  # our own posts, edits, joins …
            return
        if event.get("type") == "app_mention" or event.get("type") == "message" and self._wants_message(event):
            self._spawn(self.reply(event))

    def _wants_message(self, event: dict) -> bool:
        """Direct messages, and replies in threads the bot already answered in (mentions arrive as app_mention)."""
        if self.bot_user_id and f"<@{self.bot_user_id}>" in event.get("text", ""):
            return False
        if event.get("channel_type") == "im":
            return True
        thread_ts = event.get("thread_ts")
        return bool(thread_ts) and self.db.has_session(self.db.create_session_id(event["channel"], thread_ts))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def reply(self, event: dict) -> None:
        channel_id, user_id = event.get("channel"), event.get("user")
        thread_ts = event.get("thread_ts") or event.get("ts")
        text = event.get("text", "")
        if self.bot_user_id:
            text = text.replace(f"<@{self.bot_user_id}>", "").strip()
        if not text:
            await self.slack_client.chat_postMessage(
                channel=channel_id, thread_ts=thread_ts, text="Hi! Ask me to run something on one of your machines."
            )
            return

        session_id = self.db.create_session_id(channel_id, thread_ts)
        self.db.upsert_session(session_id, channel_id, user_id, thread_ts)
        try:
            answer = await self.process_with_context(text, session_id)
        except Exception as e:  # noqa: BLE001 - surfaced to the user
            logger.exception("Error answering")
            answer = f"Sorry, I hit an error: {e}"
        if len(answer) > SLACK_TEXT_MAX:
            answer = answer[:SLACK_TEXT_MAX] + "\n… (cut)"
        await self.slack_client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=answer, mrkdwn=True)

    async def start(self, mcp_server_url: str) -> None:
        await self.connect_to_mcp_server(mcp_server_url)
        self.bot_user_id = (await self.slack_client.auth_test())["user_id"]
        self.socket_client.socket_mode_request_listeners.append(self.handle_slack_event)
        await self.socket_client.connect()
        logger.info("Slack bot is running: direct messages, @mentions and its own threads")
        await asyncio.Event().wait()


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    server_url = args[0] if args else os.getenv("MCP_SERVER_URL")
    if not server_url:
        logger.info("Usage: python mcp_slack_client.py <MCP_SERVER_URL> [--test]")
        logger.info("Example: python mcp_slack_client.py http://localhost:8002/sse")
        sys.exit(1)

    client = SlackMCPClient()
    try:
        if "--test" in sys.argv:
            await client.connect_to_mcp_server(server_url)
            logger.info("Connected to the MCP server")
            bot_info = await client.slack_client.auth_test()
            logger.info("Connected to Slack as %s", bot_info["user"])
            logger.info("All systems operational. Run without --test to start the bot.")
        else:
            await client.start(server_url)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
