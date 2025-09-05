# Terminal MCP Server

An MCP (Model Context Protocol) server that allows AI assistants to interact with your terminal on both Mac and Windows systems.

## Features

- Execute terminal commands
- Read and write files
- Get system information
- Cross-platform support (Mac and Windows)
- Maintains working directory state

## Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd terminal-mcp

# Install in development mode
pip install -e .
Usage
With Claude Desktop
Add this to your Claude Desktop configuration file:

Mac: ~/Library/Application Support/Claude/claude_desktop_config.json Windows: %APPDATA%\Claude\claude_desktop_config.json

{
  "mcpServers": {
    "terminal": {
      "command": "python",
      "args": ["-m", "terminal_mcp.server"],
      "cwd": "/path/to/terminal-mcp"
    }
  }
}
Available Tools
run_terminal_command: Execute any terminal command
get_system_info: Get information about your system
read_file: Read the contents of a file
write_file: Write content to a file
Examples
Ask Claude to:

"Run ls command" (or dir on Windows)
"Show me the current directory"
"Create a new file called test.txt with 'Hello World'"
"Read the contents of test.txt"

## 6. Installation and Setup

1. **Create the project structure** and add all the files above.

2. **Install dependencies**:
```bash
pip install mcp
Install the MCP server:
cd terminal-mcp
pip install -e . 
```

Configure Claude Desktop:
For Mac:

```bash
# Open the config file
nano ~/Library/Application\ Support/Claude/claude_desktop_config.json
```
For Windows:
```bash
# Open the config file
notepad %APPDATA%\Claude\claude_desktop_config.json
Add this configuration:
```
{
  "mcpServers": {
    "terminal": {
      "command": "python",
      "args": ["-m", "terminal_mcp.server"],
      "cwd": "/full/path/to/terminal-mcp"
    }
  }
}
Restart Claude Desktop for the changes to take effect.
Usage Examples
Once set up, you can ask Claude to:

"Run the ls command" (it will automatically use dir on Windows)
"Show me what's in the current directory"
"Create a new Python file called hello.py"
"Navigate to the Documents folder"
"Show system information"

The server handles platform differences automatically, translating common Unix commands to Windows equivalents when needed.



uv run python -c "from fastmcp import FastMCP; mcp = FastMCP('test'); print('http_app:', hasattr(mcp, 'http_app')); print('sse_app:', hasattr(mcp, 'sse_app')); print('streamable_http_app:', hasattr(mcp, 'streamable_http_app'))"

uv run python -m src.terminal_mcp.server --transport http --host 0.0.0.0 --port 8000


#### stdio
``` bash
uv run python -m src.terminal_mcp.server
```

### http 
``` bash
uv run python -m src.terminal_mcp.server --transport http --host 0.0.0.0 --port 8000
```
### sse
uv run python -m src.terminal_mcp.server --transport sse --host 0.0.0.0 --port 8000

python client/client.py http://localhost:8000/sse/
