
<div align="center">

# TERminus
![Slack Bot](assets/BOTimage.png)

[![Medium](https://img.shields.io/badge/Medium-Part%201:%20Introducing%20Terminal%20MCP%20Server-blue?style=for-the-badge&logo=medium)](https://medium.com/@arunbh.y/introducing-terminal-mcp-server-giving-your-ai-assistant-a-terminal-superpower-23d60ecf796c)
[![Medium](https://img.shields.io/badge/Medium-Part%202:%20Building%20AI%20Powered%20Workflows-green?style=for-the-badge&logo=medium)](https://medium.com/@arunbh.y/building-ai-powered-workflows-with-terminal-mcp-and-claude-f3b932847f03)


</div>



A comprehensive terminal-based MCP (Model Context Protocol) server that enables AI assistants to interact with your system through terminal commands, file operations, and system information retrieval. TERMINUS includes both a standalone MCP server and a Slack-integrated bot for seamless terminal access.

![TERMINUS Demo](assets/Demo.gif)

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Slack Integration](#slack-integration)
- [Docker Deployment](#docker-deployment)
- [API Reference](#api-reference)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Features

### Core MCP Server
- **Terminal Command Execution**: Run any terminal command with proper working directory management
- **Cross-Platform Support**: Works on macOS, Windows, and Linux with automatic command translation
- **File Operations**: Read and write files with automatic directory creation
- **System Information**: Get detailed system information and current working directory
- **Multiple Transport Protocols**: Support for stdio, HTTP, and SSE transports

### Slack Integration
- **Real-time Chat**: Interact with your terminal through Slack messages
- **Context Awareness**: Maintains conversation history and context across sessions
- **Thread Support**: Works in both direct messages and channel threads
- **Tool Execution**: Execute terminal commands and file operations through natural language
- **Database Persistence**: SQLite-based chat history and tool call tracking

## Architecture

```mermaid
graph TB
    subgraph "Slack Workspace"
        U[User] --> SB[Slack Bot]
    end
    
    subgraph "MCP Client Layer"
        SB --> MC[MCP Client]
        MC --> AI[Claude AI]
        MC --> DB[(SQLite Database)]
    end
    
    subgraph "MCP Server Layer"
        MC --> MS[MCP Server]
        MS --> TM[Terminal Manager]
        MS --> FO[File Operations]
        MS --> SI[System Info]
    end
    
    subgraph "System Layer"
        TM --> OS[Operating System]
        FO --> FS[File System]
        SI --> HW[Hardware/OS APIs]
    end
    
    classDef slack fill:#4A154B,stroke:#fff,stroke-width:2px,color:#fff
    classDef mcp fill:#2563eb,stroke:#fff,stroke-width:2px,color:#fff
    classDef system fill:#059669,stroke:#fff,stroke-width:2px,color:#fff
    
    class U,SB slack
    class MC,AI,DB,MS,TM,FO,SI mcp
    class OS,FS,HW system
```

## Quick Start

### Prerequisites
- Python 3.12+ 
- Anthropic API key
- Slack app (for Slack integration)

### 1. Clone and Install
```bash
git clone <your-repo-url>
cd TERMINUS
pip install -e .
```

### 2. Start the MCP Server
```bash
# Using stdio transport (default)
python -m terminal_mcp.server

# Using HTTP transport
python -m terminal_mcp.server --transport http --port 8000

# Using SSE transport
python -m terminal_mcp.server --transport sse --port 8002
```

### 3. Test with Claude Desktop
Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "terminal": {
      "command": "python",
      "args": ["-m", "terminal_mcp.server"],
      "cwd": "/path/to/TERMINUS"
    }
  }
}
```

## Installation

### Method 1: Direct Installation
```bash
# Clone the repository
git clone <your-repo-url>
cd TERMINUS

# Install dependencies
pip install -r requirements.txt

# Install the MCP server
cd simple_mcp
pip install -e .
```

### Method 2: Using uv (Recommended)
```bash
# Install uv if you haven't already
pip install uv

# Install dependencies
uv sync

# Run the server
uv run python -m terminal_mcp.server
```

![UV Setup Process](assets/UV_setup.gif)

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# Required for Slack integration
ANTHROPIC_API_KEY=your_anthropic_api_key
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_APP_TOKEN=xapp-your-slack-app-token

# Optional
CLAUDE_MODEL=claude-3-5-sonnet-20241022
MCP_SERVER_URL=http://localhost:8002/sse
```

### Claude Desktop Configuration

**macOS:**
```bash
nano ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Windows:**
```bash
notepad %APPDATA%\Claude\claude_desktop_config.json
```

**Configuration:**
```json
{
  "mcpServers": {
    "terminal": {
      "command": "python",
      "args": ["-m", "terminal_mcp.server"],
      "cwd": "/full/path/to/TERMINUS/simple_mcp"
    }
  }
}
```

## Usage

### Basic Terminal Commands
Ask Claude to:
- "Run `ls -la` to show directory contents"
- "Show me the current directory"
- "Create a new file called `test.txt` with 'Hello World'"
- "Read the contents of `test.txt`"
- "Get system information"

![Running Commands](assets/RunCommands.gif)

### Advanced Operations
- "Change to the `/tmp` directory and list files"
- "Create a backup of my project folder"
- "Check disk usage with `df -h`"
- "Show running processes with `ps aux`"

### File Management
- Read files: "Show me the contents of `config.json`"
- Write files: "Create a script called `backup.sh` with the following content..."
- Directory operations: "Create a new directory called `logs`"

## Slack Integration

### Setup Slack App

1. **Create Slack App** at [api.slack.com/apps](https://api.slack.com/apps)
2. **Configure OAuth & Permissions** with these scopes:
   - `app_mentions:read`
   - `channels:history`
   - `channels:read`
   - `chat:write`
   - `im:history`
   - `im:read`
   - `im:write`
   - `users:read`

3. **Enable Event Subscriptions** with these events:
   - `app_mention`
   - `message.channels`
   - `message.im`

4. **Enable Socket Mode** and generate an App-Level Token

5. **Install App** to your workspace

For detailed setup instructions, see [Slack App Setup Guide](Slack_app_setup.md).

### Running the Slack Bot

```bash
# Start the MCP server first
python -m terminal_mcp.server --transport sse --port 8002

# In another terminal, start the Slack bot
cd simple_mcp/client
python mcp_slack_client.py http://localhost:8002/sse

# Test mode (verify connections)
python mcp_slack_client.py http://localhost:8002/sse --test
```

### Slack Bot Features
- **@mentions**: Mention the bot in any channel
- **Direct Messages**: Send DMs to the bot
- **Thread Replies**: Continue conversations in threads
- **Context Awareness**: Remembers previous commands and context
- **Rich Formatting**: Uses Slack markdown for better readability

<!-- ![Slack Bot](assets/BOTimage.png) -->

## Docker Deployment

### Using Docker Compose

```bash
# Create .env file with your tokens
cp .env.example .env
# Edit .env with your actual tokens

# Start the services
docker-compose up -d

# View logs
docker-compose logs -f
```

### Manual Docker Build

```bash
# Build the image
docker build -t terminus-slack-bot .

# Run the container
docker run -d \
  --name terminus-bot \
  -e ANTHROPIC_API_KEY=your_key \
  -e SLACK_BOT_TOKEN=your_token \
  -e SLACK_APP_TOKEN=your_app_token \
  -e MCP_SERVER_URL=http://host.docker.internal:8002/sse \
  terminus-slack-bot
```

## API Reference

### MCP Tools

#### `run_terminal_command`
Execute a command in the terminal.

**Parameters:**
- `command` (string): The command to execute
- `working_directory` (string, optional): Working directory for the command

**Example:**
```python
await run_terminal_command("ls -la", "/home/user")
```

#### `get_system_info`
Get information about the current system.

**Returns:** JSON object with system details

#### `read_file`
Read the contents of a file.

**Parameters:**
- `path` (string): Path to the file to read

#### `write_file`
Write content to a file.

**Parameters:**
- `path` (string): Path to the file to write
- `content` (string): Content to write

### Transport Options

- **stdio**: Standard input/output (default for Claude Desktop)
- **http**: HTTP REST API
- **sse**: Server-Sent Events (recommended for Slack integration)

## Development

### Project Structure
```
TERMINUS/
├── simple_mcp/                 # Main MCP server package
│   ├── src/terminal_mcp/      # Source code
│   │   ├── server.py          # MCP server implementation
│   │   └── __init__.py
│   ├── client/                # Slack client
│   │   ├── mcp_slack_client.py
│   │   ├── db_utils.py
│   │   ├── docker-compose.yaml
│   │   └── Dockerfile
│   ├── pyproject.toml         # Package configuration
│   └── README.md
├── requirements.txt           # Root dependencies
├── Slack_app_setup.md        # Slack setup guide
└── README.md                 # This file
```

### Running Tests
```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run tests
pytest
```

### Adding New Tools
1. Add tool function to `server.py` with `@mcp.tool()` decorator
2. Update documentation
3. Test with Claude Desktop or Slack bot

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Links

- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [Anthropic Claude](https://www.anthropic.com/)
- [Slack API Documentation](https://api.slack.com/)
- [FastMCP](https://github.com/pydantic/fastmcp)

---

**TERMINUS** - Bringing terminal power to AI assistants through the Model Context Protocol.
