# terminal-mcp (TERMINUS)

An MCP server that lets an AI assistant run terminal commands and read or write files, on this machine or on SSH
hosts you allow. Full guide: [TERMINUS README](../README.md).

```bash
uv sync
uv run terminal-mcp                                  # stdio, for Claude Desktop / Claude Code / Cursor
uv run terminal-mcp --ssh-hosts web1,deploy@db1      # also allow two SSH hosts
uv run terminal-mcp --transport sse --port 8002      # for the Slack bot (client/)
uv run terminal-mcp --transport http --port 8000     # Streamable HTTP at /mcp
```

Claude Code: `claude mcp add terminus -- uv run --directory /path/to/TERMINUS/simple_mcp terminal-mcp`

## Tools

Each tool takes an optional `host` (an SSH host from `list_hosts`); without it the tool acts locally.

| Tool | What it does |
|---|---|
| `list_hosts` | Local machine and allowed SSH hosts, with their working directories |
| `run_terminal_command` | Run a command (`command`, `working_directory`, `timeout`); returns exit code, stdout, stderr |
| `read_file` | Read a file (`path`, `max_bytes`) |
| `write_file` | Write or append a file (`path`, `content`, `append`) |
| `get_system_info` | OS, machine and working directory |

## Behaviour

- **SSH** uses your OpenSSH client in batch mode (keys, agent, `~/.ssh/config`, `ProxyJump`); hosts must be listed
  in `--ssh-hosts` / `TERMINUS_SSH_HOSTS` (`*` = any) and already be in `known_hosts`. Connections are shared, so
  repeat commands skip the handshake. The remote side needs `bash`.
- **Working directory** is kept per host: `cd src && make` leaves the next command in `src`.
- **Limits:** commands stop after `TERMINUS_TIMEOUT` seconds (default 60; exit code 124), output is capped at
  `TERMINUS_MAX_OUTPUT` characters (head and tail kept), reads at `TERMINUS_MAX_READ` bytes.
- **Network:** http/sse bind to `127.0.0.1`; binding elsewhere needs `--allow-remote` (there is no authentication).
  `--no-local` (or `TERMINUS_LOCAL=0`) refuses commands on the server's own machine.
- **Windows:** local commands run in `cmd.exe`; pass `working_directory` to change directory.

## Tests

```bash
uv sync --extra slack
uv run pytest
```

No network, no SSH server and no model calls are needed: SSH is exercised through a stand-in `ssh`.
