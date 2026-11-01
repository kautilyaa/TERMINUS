"""TERMINUS: an MCP server that runs terminal commands and reads/writes files on this machine or on SSH hosts.

Every tool takes an optional ``host``. Without it the tool acts on the local machine; with it the tool acts on that
SSH destination (a ``~/.ssh/config`` alias or ``user@host``), which must be on the allowlist (``--ssh-hosts`` or
``TERMINUS_SSH_HOSTS``; ``*`` allows any). SSH runs through the system's OpenSSH client in batch mode, so keys,
agents, jump hosts and ``known_hosts`` work as they do in your shell, and nothing prompts. Connections are
multiplexed (``ControlMaster``), so after the first command on a host the next ones skip the handshake.

Each host keeps its own working directory: a command that changes directory (``cd src && make``) leaves the next
command in the new one. Commands are stopped after a timeout and their output is capped.

Logs go to stderr only: on the stdio transport stdout carries the protocol.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import logging
import os
import platform
import shlex
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path

from fastmcp import FastMCP

log = logging.getLogger("terminus")

LOCAL = "local"
CWD_MARK = "\x00__TERMINUS_CWD__"  # what the shell prints after the output: a NUL keeps it apart from real output
CWD_MARK_PRINTF = "\\000__TERMINUS_CWD__"  # the same, as printf writes it (argv can't carry a NUL)
IS_WINDOWS = platform.system() == "Windows"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    timeout_s: int = _env_int("TERMINUS_TIMEOUT", 60)
    max_output: int = _env_int("TERMINUS_MAX_OUTPUT", 30_000)  # characters per stream returned to the model
    max_read: int = _env_int("TERMINUS_MAX_READ", 200_000)  # bytes read_file returns
    ssh_hosts: list[str] = field(
        default_factory=lambda: [h.strip() for h in os.environ.get("TERMINUS_SSH_HOSTS", "").split(",") if h.strip()]
    )
    ssh_bin: str = os.environ.get("TERMINUS_SSH_BIN", "ssh")
    connect_timeout_s: int = _env_int("TERMINUS_SSH_CONNECT_TIMEOUT", 10)
    control_dir: str = os.environ.get("TERMINUS_SSH_CONTROL_DIR", str(Path.home() / ".ssh" / "terminus"))
    local: bool = os.environ.get("TERMINUS_LOCAL", "1") != "0"  # allow commands on this machine


settings = Settings()
# Working directory per host; a remote host starts in its login directory (None).
cwds: dict[str, str | None] = {LOCAL: os.getcwd()}

mcp = FastMCP(
    "TERMINUS",
    instructions=(
        "Run terminal commands and read or write files on this machine or on the SSH hosts list_hosts shows. "
        "Pass host to act on an SSH host; leave it out for the local machine. Each host keeps its working "
        "directory between commands. Long-running or interactive commands are stopped after the timeout."
    ),
)


class TerminusError(Exception):
    """A refusal or failure reported to the caller as text."""


# --------------------------------------------------------------------------- hosts and command lines


def resolve_host(host: str | None) -> str:
    if not host or host == LOCAL:
        if not settings.local:
            raise TerminusError("local commands are turned off (TERMINUS_LOCAL=0); pass an SSH host")
        return LOCAL
    if host.startswith("-") or any(c.isspace() for c in host):
        raise TerminusError(f"not a valid SSH destination: {host!r}")
    if "*" not in settings.ssh_hosts and host not in settings.ssh_hosts:
        allowed = ", ".join(settings.ssh_hosts) or "none"
        raise TerminusError(f"host {host!r} is not allowed (allowed: {allowed}; set TERMINUS_SSH_HOSTS)")
    return host


def ssh_argv(host: str, remote_command: str) -> list[str]:
    """OpenSSH in batch mode with a shared connection per host."""
    Path(settings.control_dir).mkdir(mode=0o700, parents=True, exist_ok=True)
    return [
        settings.ssh_bin,
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={settings.connect_timeout_s}",
        "-o", "ControlMaster=auto",
        "-o", f"ControlPath={settings.control_dir}/%C",
        "-o", "ControlPersist=300",
        "-o", "ServerAliveInterval=15",
        "-T",
        host,
        "--",
        remote_command,
    ]  # fmt: skip


def wrap_posix(command: str, cwd: str | None) -> str:
    """The command run in ``cwd`` with its final directory appended after a marker; the exit code is kept."""
    enter = f"cd {shlex.quote(cwd)} || exit 1\n" if cwd else ""
    return f"{enter}{command}\n__terminus_rc=$?\nprintf '{CWD_MARK_PRINTF}%s' \"$PWD\"\nexit $__terminus_rc"


def split_cwd(stdout: str) -> tuple[str, str | None]:
    head, sep, tail = stdout.rpartition(CWD_MARK)
    if not sep:
        return stdout, None
    return head, tail.strip() or None


def clip(text: str, limit: int) -> str:
    """Keep the head and the tail of long output (errors usually sit at the end)."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n… [{len(text) - limit} characters cut] …\n{text[-half:]}"


# --------------------------------------------------------------------------- running


@dataclass
class Result:
    stdout: str
    stderr: str
    code: int
    timed_out: bool = False


async def _spawn(argv: list[str], *, cwd: str | None = None, stdin: bytes | None = None, timeout: float) -> Result:
    kwargs: dict = {}
    if not IS_WINDOWS:
        kwargs["start_new_session"] = True  # own process group, so a timeout kills the whole pipeline
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )
    except FileNotFoundError as e:
        raise TerminusError(f"cannot run {argv[0]}: {e.strerror}") from e
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
        timed_out = False
    except asyncio.TimeoutError:
        _kill(proc)
        out, err = await proc.communicate()
        timed_out = True
    return Result(
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
        124 if timed_out else (proc.returncode if proc.returncode is not None else -1),
        timed_out,
    )


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        if IS_WINDOWS:
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def run_on(host: str, command: str, *, timeout: float, stdin: bytes | None = None) -> Result:
    """Run ``command`` on ``host`` in its working directory and remember where it ended up."""
    if host == LOCAL and IS_WINDOWS:
        return await _spawn(["cmd.exe", "/c", command], cwd=cwds[LOCAL], stdin=stdin, timeout=timeout)
    script = wrap_posix(command, cwds.get(host))
    if host == LOCAL:
        argv = ["/bin/bash", "-c", script]
    else:
        argv = ssh_argv(host, f"bash -c {shlex.quote(script)}")
    result = await _spawn(argv, stdin=stdin, timeout=timeout)
    result.stdout, new_cwd = split_cwd(result.stdout)
    if new_cwd:
        cwds[host] = new_cwd
    elif host != LOCAL and result.code == 255:
        result.stderr = result.stderr or "ssh failed (exit 255): check the host, your key and known_hosts"
    return result


def format_result(host: str, command: str, result: Result) -> str:
    lines = [f"$ {command}", f"host: {host}  cwd: {cwds.get(host) or '~'}  exit: {result.code}"]
    if result.timed_out:
        lines.append(f"stopped after {settings.timeout_s}s timeout")
    if result.stdout:
        lines += ["", clip(result.stdout.rstrip("\n"), settings.max_output)]
    if result.stderr:
        lines += ["", "stderr:", clip(result.stderr.rstrip("\n"), settings.max_output)]
    return "\n".join(lines)


def _guard(fn):
    """Turn refusals into a plain message instead of a protocol error."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except TerminusError as e:
            return f"error: {e}"

    return wrapper


# --------------------------------------------------------------------------- tools


@mcp.tool(annotations={"readOnlyHint": True})
@_guard
async def list_hosts() -> str:
    """List where commands can run: the local machine (if enabled) and the allowed SSH hosts, with each one's
    working directory."""
    hosts = ([LOCAL] if settings.local else []) + [h for h in settings.ssh_hosts if h != "*"]
    data = {
        "hosts": [{"host": h, "cwd": cwds.get(h) or "~"} for h in hosts],
        "any_ssh_host": "*" in settings.ssh_hosts,
        "timeout_s": settings.timeout_s,
    }
    return json.dumps(data, indent=2)


@mcp.tool()
@_guard
async def run_terminal_command(
    command: str, host: str | None = None, working_directory: str | None = None, timeout: int | None = None
) -> str:
    """Run a shell command (bash) and return its exit code, stdout and stderr.

    Args:
        command: The command line, e.g. "ls -la" or "cd src && make test".
        host: An SSH host from list_hosts; omit for the local machine.
        working_directory: Run here instead of the host's current directory (also becomes the current one).
        timeout: Seconds before the command is stopped (default from the server, at most 10x that).
    """
    target = resolve_host(host)
    if working_directory:
        cwds[target] = working_directory
    limit = min(timeout or settings.timeout_s, settings.timeout_s * 10)
    result = await run_on(target, command, timeout=limit)
    return format_result(target, command, result)


@mcp.tool(annotations={"readOnlyHint": True})
@_guard
async def read_file(path: str, host: str | None = None, max_bytes: int | None = None) -> str:
    """Read a text file (relative paths are from the host's working directory).

    Args:
        path: The file to read.
        host: An SSH host from list_hosts; omit for the local machine.
        max_bytes: Read at most this many bytes (default and ceiling set by the server).
    """
    target = resolve_host(host)
    limit = min(max_bytes or settings.max_read, settings.max_read)
    q = shlex.quote(path)
    script = (
        f"test -f {q} || {{ printf 'no such file: %s\\n' {q} >&2; exit 2; }}; wc -c < {q}; head -c {limit} -- {q}"
    )
    if target == LOCAL and IS_WINDOWS:
        full = Path(cwds[LOCAL] or ".", path)
        try:
            data = await asyncio.to_thread(full.read_bytes)
        except OSError as e:
            raise TerminusError(f"cannot read {full}: {e.strerror}") from e
        size, body = len(data), data[:limit].decode("utf-8", "replace")
    else:
        result = await run_on(target, script, timeout=settings.timeout_s)
        if result.code != 0:
            raise TerminusError(result.stderr.strip() or f"reading {path} failed (exit {result.code})")
        first, _, body = result.stdout.partition("\n")
        size = int(first.strip() or 0)
    note = f" (first {limit} of {size} bytes)" if size > limit else ""
    return f"{path} on {target}{note}:\n\n{body}"


@mcp.tool()
@_guard
async def write_file(path: str, content: str, host: str | None = None, append: bool = False) -> str:
    """Write (or append) text to a file, creating its directory if needed.

    Args:
        path: The file to write (relative paths are from the host's working directory).
        content: The text to write.
        host: An SSH host from list_hosts; omit for the local machine.
        append: Append instead of replacing the file.
    """
    target = resolve_host(host)
    data = content.encode("utf-8")
    if target == LOCAL and IS_WINDOWS:
        full = Path(cwds[LOCAL] or ".", path)

        def _write() -> None:
            full.parent.mkdir(parents=True, exist_ok=True)
            with open(full, "ab" if append else "wb") as f:
                f.write(data)

        await asyncio.to_thread(_write)
    else:
        q = shlex.quote(path)
        op = ">>" if append else ">"
        script = f'mkdir -p -- "$(dirname -- {q})" && cat {op} {q}'
        result = await run_on(target, script, timeout=settings.timeout_s, stdin=data)
        if result.code != 0:
            raise TerminusError(result.stderr.strip() or f"writing {path} failed (exit {result.code})")
    return f"{'appended' if append else 'wrote'} {len(data)} bytes to {path} on {target}"


@mcp.tool(annotations={"readOnlyHint": True})
@_guard
async def get_system_info(host: str | None = None) -> str:
    """Describe the OS, machine and working directory of the local machine or an SSH host."""
    target = resolve_host(host)
    if target == LOCAL:
        info = {
            "host": LOCAL,
            "system": platform.system(),
            "node": platform.node(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "cwd": cwds[LOCAL],
        }
        return json.dumps(info, indent=2)
    result = await run_on(target, "uname -srm; hostname; whoami", timeout=settings.timeout_s)
    if result.code != 0:
        raise TerminusError(result.stderr.strip() or f"ssh to {target} failed (exit {result.code})")
    uname, node, user = (result.stdout.strip().splitlines() + ["", "", ""])[:3]
    return json.dumps({"host": target, "uname": uname, "node": node, "user": user, "cwd": cwds.get(target)}, indent=2)


# --------------------------------------------------------------------------- entry point


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="TERMINUS terminal MCP server")
    parser.add_argument("--transport", choices=["stdio", "http", "sse"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="bind address for http/sse")
    parser.add_argument("--port", type=int, default=8000, help="port for http/sse")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="allow binding http/sse to a non-loopback address (anyone who reaches it can run commands)",
    )
    parser.add_argument("--ssh-hosts", help="comma-separated SSH destinations commands may run on ('*' = any)")
    parser.add_argument("--no-local", action="store_true", help="refuse commands on this machine (SSH only)")
    parser.add_argument("--timeout", type=int, help=f"command timeout in seconds (default {settings.timeout_s})")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(message)s")
    if args.ssh_hosts is not None:
        settings.ssh_hosts = [h.strip() for h in args.ssh_hosts.split(",") if h.strip()]
    if args.no_local:
        settings.local = False
    if args.timeout:
        settings.timeout_s = args.timeout

    if args.transport == "stdio":
        mcp.run(transport="stdio", show_banner=False)
        return
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        parser.error(f"--host {args.host} exposes command execution on the network; add --allow-remote to confirm")
    log.info("TERMINUS on %s://%s:%s (ssh hosts: %s)", args.transport, args.host, args.port, settings.ssh_hosts)
    mcp.run(transport=args.transport, host=args.host, port=args.port, show_banner=False)


if __name__ == "__main__":
    main()
