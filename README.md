
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
- **Terminal Command Execution**: Run any shell command; each host keeps its working directory, so `cd src && make` leaves the next command in `src`
- **SSH Hosts**: Run commands and read/write files on remote machines through your own OpenSSH setup (keys, agent, `~/.ssh/config` aliases, jump hosts), limited to an allowlist
- **Fast Repeat SSH Calls**: Connections are multiplexed (`ControlMaster`), so only the first command on a host pays for the handshake
- **Safe Defaults**: Commands stop at a timeout (whole process group), long output keeps its head and tail, file reads are capped, and HTTP/SSE bind to loopback unless you opt in
- **File Operations**: Read (with a byte cap) and write or append files, creating directories as needed
- **System Information**: OS, machine and working directory for the local machine or any SSH host
- **Multiple Transport Protocols**: stdio (default), Streamable HTTP and SSE

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
- Python 3.10+ and [uv](https://docs.astral.sh/uv/) (or pip)
- OpenSSH client, for SSH hosts
- Anthropic API key and a Slack app (only for the Slack bot)

### 1. Clone and Install
```bash
git clone https://github.com/kautilyaa/TERMINUS.git
cd TERMINUS/simple_mcp
uv sync
```

### 2. Start the MCP Server
```bash
cd simple_mcp

# stdio (default; for Claude Desktop, Claude Code, Cursor …)
uv run terminal-mcp

# Streamable HTTP on http://127.0.0.1:8000/mcp
uv run terminal-mcp --transport http --port 8000

# SSE on http://127.0.0.1:8002/sse (used by the Slack bot)
uv run terminal-mcp --transport sse --port 8002

# Allow two SSH hosts (aliases from ~/.ssh/config or user@host)
uv run terminal-mcp --ssh-hosts web1,deploy@db1
```

### 3. Test with Claude Desktop
Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "terminal": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/TERMINUS/simple_mcp", "terminal-mcp", "--ssh-hosts", "web1,db1"]
    }
  }
}
```

Or with Claude Code: `claude mcp add terminus -- uv run --directory /path/to/TERMINUS/simple_mcp terminal-mcp`.

## Installation

### Method 1: pip
```bash
git clone https://github.com/kautilyaa/TERMINUS.git
cd TERMINUS/simple_mcp
pip install -e .             # the server (needs only fastmcp)
pip install -e ".[slack]"    # plus the Slack bot's dependencies
terminal-mcp --help
```

### Method 2: Using uv (Recommended)
```bash
cd TERMINUS/simple_mcp
uv sync                      # add --extra slack for the Slack bot
uv run terminal-mcp
```

![UV Setup Process](assets/UV_setup.gif)

## Configuration

### Server options

Every option has a flag and an environment variable:

| Flag | Environment | Default | Meaning |
|---|---|---|---|
| `--transport` | | `stdio` | `stdio`, `http` (Streamable HTTP at `/mcp`) or `sse` (at `/sse`) |
| `--host`, `--port` | | `127.0.0.1`, `8000` | Bind address for http/sse |
| `--allow-remote` | | off | Required to bind http/sse to a non-loopback address |
| `--ssh-hosts` | `TERMINUS_SSH_HOSTS` | none | Comma-separated SSH destinations commands may run on; `*` allows any |
| `--no-local` | `TERMINUS_LOCAL=0` | local on | Refuse commands on the server's own machine (SSH only) |
| `--timeout` | `TERMINUS_TIMEOUT` | `60` | Seconds before a command is stopped (a call may ask for up to 10x) |
| | `TERMINUS_MAX_OUTPUT` | `30000` | Characters of stdout/stderr returned (head and tail kept) |
| | `TERMINUS_MAX_READ` | `200000` | Bytes `read_file` returns at most |
| | `TERMINUS_SSH_CONNECT_TIMEOUT` | `10` | SSH connect timeout in seconds |
| | `TERMINUS_SSH_CONTROL_DIR` | `~/.ssh/terminus` | Where the shared SSH connection sockets live |
| | `TERMINUS_SSH_BIN` | `ssh` | The OpenSSH client to use |

### SSH hosts

TERMINUS runs `ssh` in batch mode (`BatchMode=yes`), so it never prompts: the host must be reachable with a key
(or your SSH agent) and already be in `known_hosts`. Anything in `~/.ssh/config` applies: users, ports, identity
files, `ProxyJump`. Check a host first with `ssh -o BatchMode=yes web1 true`.

The remote side needs `bash`. Each host starts in its login directory and keeps its own working directory across
commands. Connections are shared for 5 minutes after the last command (`ControlPersist=300`).

### Security

TERMINUS executes whatever the model asks for, as the user running the server. Keep it to machines and accounts
you are willing to hand to the assistant:
- list only the SSH hosts it needs (avoid `*`), and prefer a low-privilege remote user;
- keep http/sse on loopback; `--allow-remote` exposes command execution to anyone who can reach the port (there is
  no authentication);
- `--no-local` keeps the server's own machine out of reach when it should only manage remote hosts.

### Slack bot environment

Create a `.env` file next to `mcp_slack_client.py`:

```bash
# Required
ANTHROPIC_API_KEY=your_anthropic_api_key
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_APP_TOKEN=xapp-your-slack-app-token

# Optional
CLAUDE_MODEL=claude-sonnet-4-5
MCP_SERVER_URL=http://localhost:8002/sse   # used when no URL is passed on the command line
DB_PATH=chat_history.db
LOG_FILE=                                    # also log to this file
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

### Remote Machines (SSH)
- "Which hosts can you reach?" (`list_hosts`)
- "On `web1`, show the last 50 lines of `/var/log/nginx/error.log`"
- "Check free memory and disk on `db1`"
- "Go to `/srv/app` on `web1` and run `git status`"

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
cd simple_mcp
uv run terminal-mcp --transport sse --port 8002 --ssh-hosts web1,db1

# In another terminal, start the Slack bot
uv sync --extra slack
uv run python client/mcp_slack_client.py http://localhost:8002/sse

# Test mode (verify connections)
uv run python client/mcp_slack_client.py http://localhost:8002/sse --test
```

A Streamable HTTP server works too: pass `http://localhost:8000/mcp`.

### Slack Bot Features
- **@mentions**: Mention the bot in any channel; it answers in a thread
- **Direct Messages**: Send DMs to the bot
- **Thread Replies**: Keeps answering in threads it is part of (one reply per message, even when mentioned again)
- **Context Awareness**: Each thread is one conversation, shared by everyone in it
- **Parallel Tools**: Independent tool calls in one turn run at the same time
- **Rich Formatting**: Uses Slack markdown for better readability

<!-- ![Slack Bot](assets/BOTimage.png) -->

## Docker Deployment

### Using Docker Compose

```bash
cd simple_mcp/client
# Create .env with your tokens, then:
docker compose up -d
docker compose logs -f
```

The bot reaches the server on the host at `host.docker.internal:8002`. On Docker Desktop that works with the
server on loopback; on Linux start the server with `--host 0.0.0.0 --allow-remote` and firewall the port.

### Manual Docker Build

```bash
cd simple_mcp/client
docker build -t terminus-slack-bot .
docker run -d \
  --name terminus-bot \
  -e ANTHROPIC_API_KEY=your_key \
  -e SLACK_BOT_TOKEN=your_token \
  -e SLACK_APP_TOKEN=your_app_token \
  -e MCP_SERVER_URL=http://host.docker.internal:8002/sse \
  -v "$PWD/data:/app/data" \
  terminus-slack-bot
```

## API Reference

### MCP Tools

Every tool takes an optional `host`: an SSH host from `list_hosts`. Leave it out to act on the server's machine.

#### `list_hosts`
Where commands can run (the local machine and the allowed SSH hosts), with each host's working directory.

#### `run_terminal_command`
Run a shell command and return its exit code, stdout and stderr.

**Parameters:**
- `command` (string): The command line, e.g. `cd src && make test`
- `host` (string, optional): SSH host
- `working_directory` (string, optional): Run here (it also becomes the host's working directory)
- `timeout` (integer, optional): Seconds before the command is stopped (up to 10x the server default)

A stopped command reports exit code `124`.

#### `read_file`
Read a text file. **Parameters:** `path`, `host` (optional), `max_bytes` (optional, capped by the server).

#### `write_file`
Write or append text. **Parameters:** `path`, `content`, `host` (optional), `append` (optional). Returns the
number of bytes written.

#### `get_system_info`
OS, machine and working directory. **Parameters:** `host` (optional).

`list_hosts`, `read_file` and `get_system_info` are marked read-only (`readOnlyHint`), so clients can allow them
without asking.

### Transport Options

- **stdio**: Standard input/output (default; Claude Desktop, Claude Code, Cursor)
- **http**: Streamable HTTP at `/mcp`
- **sse**: Server-Sent Events at `/sse` (used by the Slack bot)

## Development

### Project Structure
```
TERMINUS/
├── simple_mcp/                 # Main MCP server package
│   ├── src/terminal_mcp/
│   │   ├── server.py          # MCP server (local + SSH)
│   │   └── __init__.py
│   ├── client/                # Slack bot
│   │   ├── mcp_slack_client.py
│   │   ├── db_utils.py        # chat history stats/export/cleanup
│   │   ├── requirements.txt
│   │   ├── docker-compose.yaml
│   │   └── Dockerfile
│   ├── tests/                 # pytest suite (no network, no model calls)
│   ├── pyproject.toml
│   └── README.md
├── Slack_app_setup.md         # Slack setup guide
└── README.md                  # This file
```

### Running Tests
```bash
cd simple_mcp
uv sync --extra slack
uv run pytest
```

The SSH tests use a stand-in `ssh` that runs the remote command line locally, so they need no SSH server.

### Adding New Tools
1. Add an async function to `server.py` with `@mcp.tool()` (and `@_guard` to turn refusals into messages)
2. Accept `host: str | None = None` and run through `run_on()` so it works locally and over SSH
3. Add a test in `tests/test_server.py` and update this README

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
