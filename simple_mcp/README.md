# Terminal MCP Server

A Model Context Protocol (MCP) server that enables AI assistants to interact with your terminal through command execution, file operations, and system information retrieval. This server provides cross-platform support for macOS, Windows, and Linux systems.

## Features

- **Terminal Command Execution**: Run any terminal command with proper working directory management
- **File Operations**: Read and write files with automatic directory creation
- **System Information**: Get detailed system information and current working directory
- **Cross-Platform Support**: Works on macOS, Windows, and Linux with automatic command translation
- **Multiple Transport Protocols**: Support for stdio, HTTP, and SSE transports

## Installation

### Prerequisites
- Python 3.12+
- MCP client (Claude Desktop, or custom client)

### Install Dependencies

```bash
# Install MCP dependencies
pip install mcp fastmcp

# Install the MCP server in development mode
pip install -e .
```

### Using uv (Recommended)

```bash
# Install uv if you haven't already
pip install uv

# Install dependencies
uv sync

# Run the server
uv run python -m terminal_mcp.server
```

## Usage

### Transport Options

#### stdio (Default for Claude Desktop)
```bash
python -m terminal_mcp.server
```

#### HTTP Transport
```bash
python -m terminal_mcp.server --transport http --host 0.0.0.0 --port 8000
```

#### SSE Transport
```bash
python -m terminal_mcp.server --transport sse --host 0.0.0.0 --port 8002
```

### Claude Desktop Configuration

Add this to your Claude Desktop configuration file:

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
      "cwd": "/full/path/to/terminal-mcp"
    }
  }
}
```

## Available Tools

### `run_terminal_command`
Execute any terminal command with optional working directory specification.

**Parameters:**
- `command` (string): The command to execute
- `working_directory` (string, optional): Working directory for the command

### `get_system_info`
Get comprehensive information about the current system.

**Returns:** JSON object with system details including OS, architecture, Python version, and current directory.

### `read_file`
Read the contents of a file.

**Parameters:**
- `path` (string): Path to the file to read

### `write_file`
Write content to a file with automatic directory creation.

**Parameters:**
- `path` (string): Path to the file to write
- `content` (string): Content to write

## Usage Examples

Ask Claude to:

- "Run `ls -la` to show directory contents"
- "Show me the current directory"
- "Create a new file called `test.txt` with 'Hello World'"
- "Read the contents of `test.txt`"
- "Get system information"
- "Change to the `/tmp` directory and list files"
- "Create a backup of my project folder"

## Cross-Platform Support

The server automatically handles platform differences:

- **Windows**: Translates common Unix commands (`ls` → `dir`, `pwd` → `cd`, etc.)
- **macOS/Linux**: Uses standard Unix commands
- **Working Directory**: Maintains state across commands
- **Path Handling**: Supports both relative and absolute paths

## Development

### Project Structure
```
simple_mcp/
├── src/terminal_mcp/          # Source code
│   ├── server.py              # MCP server implementation
│   └── __init__.py
├── client/                    # Slack client (optional)
│   ├── mcp_slack_client.py
│   └── requirements.txt
├── pyproject.toml             # Package configuration
└── README.md                  # This file
```

### Testing the Server

```bash
# Test stdio transport
python -m terminal_mcp.server

# Test HTTP transport
python -m terminal_mcp.server --transport http --port 8000

# Test SSE transport
python -m terminal_mcp.server --transport sse --port 8002
```

### Integration with Slack Bot

To use with the Slack bot client:

```bash
# Start the MCP server with SSE transport
python -m terminal_mcp.server --transport sse --port 8002

# In another terminal, start the Slack client
cd client
python mcp_slack_client.py http://localhost:8002/sse
```

## License

This project is part of TERMINUS and is licensed under the MIT License.