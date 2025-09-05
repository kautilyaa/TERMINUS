#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import logging
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
import hashlib

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client
from anthropic import Anthropic
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("mcp_slack_client.log")
    ]
)
logger = logging.getLogger("MCP-Slack-Client")


class ChatDatabase:
    """SQLite database for tracking chat history"""
    
    def __init__(self, db_path: str = "chat_history.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Chat sessions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    thread_ts TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Messages table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
                )
            ''')
            
            # Tool calls table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    input_params TEXT,
                    output TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
                )
            ''')
            
            conn.commit()
    
    def create_session_id(self, channel_id: str, user_id: str, thread_ts: Optional[str] = None) -> str:
        """Generate unique session ID"""
        components = f"{channel_id}:{user_id}:{thread_ts or 'main'}"
        return hashlib.md5(components.encode()).hexdigest()
    
    def save_message(self, session_id: str, role: str, content: str, metadata: Optional[Dict] = None):
        """Save a message to the database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO messages (session_id, role, content, metadata)
                VALUES (?, ?, ?, ?)
            ''', (session_id, role, content, json.dumps(metadata) if metadata else None))
            conn.commit()
    
    def save_tool_call(self, session_id: str, tool_name: str, input_params: Dict, 
                      output: str, status: str = "success"):
        """Save tool call information"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tool_calls (session_id, tool_name, input_params, output, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, tool_name, json.dumps(input_params), output, status))
            conn.commit()
    
    def get_session_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Retrieve recent conversation history"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT role, content, created_at 
                FROM messages 
                WHERE session_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (session_id, limit))
            
            rows = cursor.fetchall()
            return [
                {"role": row[0], "content": row[1], "timestamp": row[2]}
                for row in reversed(rows)
            ]
    
    def upsert_session(self, session_id: str, channel_id: str, user_id: str, 
                      thread_ts: Optional[str] = None):
        """Create or update a chat session"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO chat_sessions 
                (session_id, channel_id, user_id, thread_ts, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (session_id, channel_id, user_id, thread_ts))
            conn.commit()


class SlackMCPClient:
    """
    Slack-integrated MCP client with Claude AI
    """
    
    def __init__(self, model: str = "claude-3-5-sonnet-20241022"):
        self.model = model
        self.session: Optional[ClientSession] = None
        self.db = ChatDatabase()
        
        # Initialize Anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        self.claude = Anthropic(api_key=api_key)
        
        # Initialize Slack clients
        self.slack_token = os.getenv("SLACK_BOT_TOKEN")
        self.slack_app_token = os.getenv("SLACK_APP_TOKEN")
        
        if not self.slack_token or not self.slack_app_token:
            raise ValueError("SLACK_BOT_TOKEN and SLACK_APP_TOKEN are required")
        
        self.slack_client = AsyncWebClient(token=self.slack_token)
        self.socket_client = SocketModeClient(
            app_token=self.slack_app_token,
            web_client=self.slack_client
        )
        
        # Track active conversations
        self.active_threads: Dict[str, Dict] = {}
        
    async def connect_to_mcp_server(self, server_url: str):
        """Connect to MCP server"""
        logger.info(f"Connecting to MCP server at {server_url}")
        self._streams_context = sse_client(url=server_url)
        streams = await self._streams_context.__aenter__()
        self._session_context = ClientSession(*streams)
        self.session = await self._session_context.__aenter__()
        await self.session.initialize()
        
        # Log available tools
        resp = await self.session.list_tools()
        tool_names = [t.name for t in resp.tools]
        logger.info(f"Connected to MCP. Available tools: {tool_names}")
    
    async def cleanup(self):
        """Cleanup resources"""
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
        """Convert MCP tools to Anthropic format"""
        tools = []
        for t in mcp_tools:
            tools.append({
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema or {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True
                },
            })
        return tools
    
    async def process_with_context(self, query: str, session_id: str, 
                                  channel_id: str, user_id: str) -> str:
        """Process query with conversation context"""
        
        # Save user message
        self.db.save_message(session_id, "user", query)
        
        # Get conversation history for context
        history = self.db.get_session_history(session_id, limit=5)
        
        # Build context-aware system prompt
        system_prompt = (
            "You are an expert Terminal Operations Assistant integrated with Slack. "
            "You can use MCP tools to inspect and manage infrastructure. "
            "Be concise but informative in your responses, suitable for Slack messages. "
            "Use Slack formatting for better readability."
        )
        
        # Build messages with history
        messages: List[Dict[str, Any]] = []
        
        # Add historical context if available
        for msg in history[:-1]:  # Exclude the current message we just saved
            content = [{"type": "text", "text": msg["content"]}]
            messages.append({"role": msg["role"], "content": content})
        
        # Add current query
        messages.append({"role": "user", "content": [{"type": "text", "text": query}]})
        
        # Get tools from MCP
        resp = await self.session.list_tools()
        tools = self._anthropic_tools_from_mcp(resp.tools)
        
        MAX_TURNS = 10
        for turn in range(MAX_TURNS):
            try:
                # Call Claude with tools
                response = self.claude.messages.create(
                    model=self.model,
                    system=system_prompt,
                    tools=tools,
                    tool_choice={"type": "auto"},
                    max_tokens=4096,
                    temperature=0.1,
                    messages=messages,
                )
                
                assistant_content = response.content
                tool_uses = [b for b in assistant_content if hasattr(b, 'type') and b.type == "tool_use"]
                
                # Convert content to dict format
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
                
                messages.append({"role": "assistant", "content": assistant_content_dicts})
                
                if tool_uses:
                    # Execute tool calls
                    tool_results_blocks: List[Dict[str, Any]] = []
                    
                    for tu in tool_uses:
                        tool_name = tu.name
                        tool_use_id = tu.id
                        tool_input = tu.input if hasattr(tu, 'input') else {}
                        
                        logger.info(f"Executing tool '{tool_name}'")
                        
                        try:
                            mcp_result = await self.session.call_tool(tool_name, tool_input)
                            
                            if isinstance(mcp_result, list) and mcp_result:
                                part = mcp_result[0]
                                result_text = getattr(part, "text", None) or json.dumps(mcp_result, default=str)[:10000]
                            else:
                                result_text = str(mcp_result)[:10000]
                            
                            # Save tool call to database
                            self.db.save_tool_call(session_id, tool_name, tool_input, result_text)
                            
                        except Exception as e:
                            result_text = f"Error executing tool '{tool_name}': {e}"
                            logger.error(result_text)
                            self.db.save_tool_call(session_id, tool_name, tool_input, str(e), "error")
                        
                        tool_results_blocks.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": [{"type": "text", "text": result_text}]
                        })
                    
                    messages.append({"role": "user", "content": tool_results_blocks})
                    continue
                
                # Extract final text response
                text_blocks = [b for b in assistant_content if hasattr(b, 'type') and b.type == "text"]
                final_text = "\n".join([b.text for b in text_blocks]).strip() if text_blocks else "(No response)"
                
                # Save assistant response
                self.db.save_message(session_id, "assistant", final_text)
                
                return final_text
                
            except Exception as e:
                logger.error(f"Error processing query: {e}")
                return f" Error: {str(e)}"
        
        return "Conversation exceeded maximum turns."
    
    async def handle_slack_event(self, client: SocketModeClient, req: SocketModeRequest):
        """Handle incoming Slack events"""
        
        if req.type == "events_api":
            # Acknowledge the request
            response = SocketModeResponse(envelope_id=req.envelope_id)
            await client.send_socket_mode_response(response)
            
            event = req.payload.get("event", {})
            event_type = event.get("type")
            
            # Handle different event types
            if event_type == "app_mention":
                await self.handle_mention(event)
            elif event_type == "message":
                # Only handle direct messages or if bot is in thread
                if event.get("channel_type") == "im" or event.get("thread_ts"):
                    await self.handle_message(event)
    
    async def handle_mention(self, event: Dict):
        """Handle @mentions of the bot"""
        channel_id = event.get("channel")
        user_id = event.get("user")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        
        # Remove bot mention from text
        bot_id = await self.get_bot_id()
        text = text.replace(f"<@{bot_id}>", "").strip()
        
        if not text:
            await self.slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Hi! How can I help you? You can ask me about Terminal resources, logs, or infrastructure."
            )
            return
        
        # Send typing indicator
        await self.send_typing_indicator(channel_id)
        
        # Create session and process
        session_id = self.db.create_session_id(channel_id, user_id, thread_ts)
        self.db.upsert_session(session_id, channel_id, user_id, thread_ts)
        
        try:
            response = await self.process_with_context(text, session_id, channel_id, user_id)
            
            # Send response in thread
            await self.slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=response,
                mrkdwn=True
            )
            
        except Exception as e:
            logger.error(f"Error handling mention: {e}")
            await self.slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f" Sorry, I encountered an error: {str(e)}"
            )
    
    async def handle_message(self, event: Dict):
        """Handle direct messages"""
        
        # Ignore bot's own messages
        if event.get("bot_id"):
            return
        
        channel_id = event.get("channel")
        user_id = event.get("user")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts")
        
        if not text:
            return
        
        # Send typing indicator
        await self.send_typing_indicator(channel_id)
        
        # Create session and process
        session_id = self.db.create_session_id(channel_id, user_id, thread_ts)
        self.db.upsert_session(session_id, channel_id, user_id, thread_ts)
        
        try:
            response = await self.process_with_context(text, session_id, channel_id, user_id)
            
            # Send response
            await self.slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts or event.get("ts"),
                text=response,
                mrkdwn=True
            )
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await self.slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts or event.get("ts"),
                text=f" Sorry, I encountered an error: {str(e)}"
            )
    
    async def send_typing_indicator(self, channel: str):
        """Send typing indicator to show bot is processing"""
        try:
            # Slack doesn't have a direct typing indicator for bots,
            # but we can add a reaction as feedback
            pass
        except Exception as e:
            logger.error(f"Error sending typing indicator: {e}")
    
    async def get_bot_id(self) -> str:
        """Get the bot's user ID"""
        response = await self.slack_client.auth_test()
        return response["user_id"]
    
    async def start(self, mcp_server_url: str):
        """Start the Slack bot"""
        
        # Connect to MCP server
        await self.connect_to_mcp_server(mcp_server_url)
        
        # Set up event handler
        self.socket_client.socket_mode_request_listeners.append(self.handle_slack_event)
        
        # Connect to Slack
        await self.socket_client.connect()
        
        logger.info("Slack bot started and listening for events")
        logger.info("Slack MCP Bot is running!")
        logger.info("The bot will respond to:")
        logger.info("  - Direct messages")
        logger.info("  - @mentions in channels")
        logger.info("  - Thread replies")
        
        # Keep the bot running
        await asyncio.Event().wait()


async def main():
    if len(sys.argv) < 2:
        logger.info("Usage: python mcp_slack_client.py <MCP_SERVER_URL>")
        logger.info("Example: python mcp_slack_client.py http://localhost:8002/sse")
        sys.exit(1)
    
    server_url = sys.argv[1]
    
    # Check for test mode
    test_mode = "--test" in sys.argv
    
    client = SlackMCPClient(
        model=os.getenv("CLAUDE_MODEL", "claude-3-7-sonnet-20250219")
    )
    
    try:
        if test_mode:
            # Test mode: just verify connections
            await client.connect_to_mcp_server(server_url)
            logger.info(" Successfully connected to MCP server!")
            
            # Test Slack connection
            bot_info = await client.slack_client.auth_test()
            logger.info(f" Successfully connected to Slack as {bot_info['user']}")
            
            # Test database
            test_session = client.db.create_session_id("test", "test", "test")
            client.db.save_message(test_session, "user", "Test message")
            logger.info(" Database initialized successfully")
            
            logger.info("\nAll systems operational! Run without --test to start the bot.")
        else:
            # Normal operation
            await client.start(server_url)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())