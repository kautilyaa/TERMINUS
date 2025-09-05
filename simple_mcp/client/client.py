#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import logging
from typing import Optional, List, Dict, Any
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client
from anthropic import Anthropic

# Load env
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("aws_mcp_client.log")]
)
logger = logging.getLogger("MCP-Claude-Client")


class ClaudeMCPClient:
    """
    Interactive MCP client that uses Anthropic Claude Messages API (no AWS).
    - Connects to MCP server via SSE.
    - Exposes MCP tools to Claude.
    - Executes tool calls and streams results back until final text is produced.
    """
    def __init__(self, model: str = "claude-3-5-sonnet-20240620"):
        self.model = model
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        self.claude = Anthropic(api_key=api_key)

    async def connect_to_sse_server(self, server_url: str):
        logger.info(f"Connecting to MCP server at {server_url}")
        self._streams_context = sse_client(url=server_url)
        streams = await self._streams_context.__aenter__()
        self._session_context = ClientSession(*streams)
        self.session = await self._session_context.__aenter__()
        await self.session.initialize()

        # Verify tool availability
        resp = await self.session.list_tools()
        tool_names = [t.name for t in resp.tools]
        logger.info(f"Connected. Tools: {tool_names}")
        print(f"\nConnected to MCP with tools: {', '.join(tool_names)}")

    async def cleanup(self):
        try:
            if hasattr(self, "_session_context") and self._session_context:
                await self._session_context.__aexit__(None, None, None)
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")
        try:
            if hasattr(self, "_streams_context") and self._streams_context:
                await self._streams_context.__aexit__(None, None, None)
        except Exception as e:
            logger.error(f"Streams cleanup error: {e}")

    def _anthropic_tools_from_mcp(self, mcp_tools) -> List[Dict[str, Any]]:
        """
        Convert MCP tool descriptors to Anthropic tool schema.
        MCP provides: name, description, inputSchema (JSON Schema).
        Anthropic expects: {"name","description","input_schema":{...}}
        """
        tools = []
        for t in mcp_tools:
            tools.append({
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema or {"type": "object", "properties": {}, "additionalProperties": True},
            })
        return tools
    async def process_query(self, query: str) -> str:
        """
        Multi-turn loop:
        - Ask Claude with tool schemas.
        - If 'tool_use' is returned, call the MCP tool and send back 'tool_result'.
        - Repeat until Claude returns plain text.
        """
        # Build system prompt
        system_prompt = (
            "You are an expert AWS Operations Assistant that can use MCP tools to inspect "
            "and manage infrastructure, fetch logs, and summarize issues. Prefer precise, "
            "actionable answers. If you need data, call tools."
        )

        # Get tools from MCP and map to Anthropic schema
        resp = await self.session.list_tools()
        tools = self._anthropic_tools_from_mcp(resp.tools)

        # Conversation state for Anthropic
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": query}]}
        ]

        MAX_TURNS = 100
        for turn in range(MAX_TURNS):
            try:
                # Create a message with tool affordances
                response = self.claude.messages.create(
                    model=self.model,
                    system=system_prompt,
                    tools=tools,
                    tool_choice={"type": "auto"},
                    max_tokens=4096,
                    temperature=0.1,
                    messages=messages,
                )

                # Parse assistant content - these are objects, not dicts
                assistant_content = response.content  # list of content blocks
                
                # Check if assistant is asking for tool use
                # Need to check the type attribute of each block object
                tool_uses = [b for b in assistant_content if hasattr(b, 'type') and b.type == "tool_use"]
                
                # Convert content blocks to dict format for messages history
                assistant_content_dicts = []
                for block in assistant_content:
                    if hasattr(block, 'type'):
                        if block.type == "text":
                            assistant_content_dicts.append({
                                "type": "text",
                                "text": block.text
                            })
                        elif block.type == "tool_use":
                            assistant_content_dicts.append({
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input
                            })

                # Always append assistant message to history
                messages.append({"role": "assistant", "content": assistant_content_dicts})

                if tool_uses:
                    # Execute each tool call via MCP and attach tool_result
                    tool_results_blocks: List[Dict[str, Any]] = []
                    for tu in tool_uses:
                        tool_name = tu.name  # Access as attribute, not dict key
                        tool_use_id = tu.id
                        tool_input = tu.input if hasattr(tu, 'input') else {}

                        logger.info(f"Executing tool '{tool_name}' with input: {tool_input}")
                        try:
                            mcp_result = await self.session.call_tool(tool_name, tool_input)
                            # mcp_result often returns a list of content parts; convert to readable text
                            if isinstance(mcp_result, list) and mcp_result:
                                # Try to surface the first text-like payload or JSON stringify
                                part = mcp_result[0]
                                result_text = getattr(part, "text", None) or json.dumps(mcp_result, default=str)[:10000]
                            else:
                                result_text = str(mcp_result)[:10000]
                            logger.info(f"Tool '{tool_name}' executed successfully")
                        except Exception as e:
                            result_text = f"Error executing tool '{tool_name}': {e}"
                            logger.error(result_text)

                        tool_results_blocks.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": [{"type": "text", "text": result_text}]
                        })

                    # Provide all tool results as a single user turn; Claude will continue
                    messages.append({"role": "user", "content": tool_results_blocks})
                    # Loop continues to next Claude call
                    continue

                # No tool uses → return text blocks as final
                text_blocks = [b for b in assistant_content if hasattr(b, 'type') and b.type == "text"]
                final_text = "\n".join([b.text for b in text_blocks]).strip() if text_blocks else "(No text returned.)"
                return final_text

            except Exception as e:
                logger.error(f"Anthropic API error: {e}")
                return f"Error calling Claude: {e}"

        return "Conversation exceeded maximum turns."

    def _show_recent_logs(self):
        try:
            with open("aws_mcp_client.log", "r") as f:
                lines = f.readlines()[-20:]
            print("\nRecent log entries:\n" + "-"*50)
            for line in lines:
                print(line.rstrip())
            print("-"*50)
        except FileNotFoundError:
            print("No log file found yet.")
        except Exception as e:
            print(f"Error reading logs: {e}")

    async def chat_loop(self):
        print("\nClaude MCP Client Started!")
        print("Commands: 'tools', 'logs', 'exit'\n" + "-"*50)
        while True:
            try:
                q = input("\nQuery: ").strip()
                if q.lower() in ("exit", "quit"):
                    print("Goodbye!")
                    break
                if q.lower() == "tools":
                    resp = await self.session.list_tools()
                    print("\nAvailable tools:")
                    for t in resp.tools:
                        print(f"- {t.name}: {t.description}")
                    continue
                if q.lower() == "logs":
                    self._show_recent_logs()
                    continue
                if not q:
                    continue

                print("\nProcessing...")
                ans = await self.process_query(q)
                print(f"\nResponse:\n{ans}")
            except KeyboardInterrupt:
                print("\nInterrupted.")
                break
            except Exception as e:
                logger.error(f"Loop error: {e}")
                print(f"Error: {e}")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python mcp_claude_client.py <MCP_SERVER_URL> [--test]")
        print("Example: python mcp_claude_client.py http://localhost:8002/sse")
        print("Add --test flag to run a simple connectivity test")
        sys.exit(1)

    server_url = sys.argv[1]
    test_mode = len(sys.argv) > 2 and sys.argv[2] == "--test"
    
    client = ClaudeMCPClient(model=os.getenv("CLAUDE_MODEL", "claude-3-7-sonnet-20250219"))

    try:
        await client.connect_to_sse_server(server_url)
        if test_mode:
            print("Successfully connected to MCP server!")
            print("Test query: What system am I running on?")
            response = await client.process_query("What system am I running on?")
            print(f"Response: {response}")
            print("Test completed successfully!")
        else:
            await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())