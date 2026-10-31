"""TERMINUS server behaviour through a real MCP client (in memory), plus the stdio transport end to end.

SSH is exercised with a stand-in ``ssh`` that runs the remote command line in a local shell, so the quoting, the
working-directory tracking and the stdin path go through the same code as a real host.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest
from fastmcp import Client

from terminal_mcp import server

FAKE_SSH = """#!/bin/sh
# Stand-in for OpenSSH: skip options up to "--", drop the destination's position, run the remote command locally.
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
shift
exec /bin/sh -c "$1"
"""


@pytest.fixture(autouse=True)
def fresh_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = tmp_path / "fake-ssh"
    fake.write_text(FAKE_SSH)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(server, "settings", server.Settings())
    server.settings.ssh_bin = str(fake)
    server.settings.ssh_hosts = ["box"]
    server.settings.control_dir = str(tmp_path / "ctl")
    server.settings.timeout_s = 5
    monkeypatch.setattr(server, "cwds", {server.LOCAL: str(tmp_path)})
    server.cwds["box"] = str(tmp_path)  # the stand-in host's "login directory"
    return tmp_path


async def call(tool: str, **args) -> str:
    async with Client(server.mcp) as client:
        result = await client.call_tool(tool, args)
    return result.content[0].text


async def test_cd_anywhere_in_a_command_moves_the_working_directory(fresh_state: Path):
    (fresh_state / "sub").mkdir()
    out = await call("run_terminal_command", command="cd sub && echo moved")
    assert "moved" in out and "exit: 0" in out
    out = await call("run_terminal_command", command="pwd")
    assert out.splitlines()[-1] == str((fresh_state / "sub").resolve())


async def test_exit_code_and_stderr_come_back():
    out = await call("run_terminal_command", command="echo oops >&2; exit 3")
    assert "exit: 3" in out
    assert out.endswith("stderr:\noops")


async def test_a_hanging_pipeline_is_stopped_at_the_timeout():
    started = time.monotonic()
    out = await call("run_terminal_command", command="sleep 30 | cat", timeout=1)
    assert time.monotonic() - started < 5
    assert "exit: 124" in out and "timeout" in out


async def test_long_output_keeps_head_and_tail():
    server.settings.max_output = 1000
    out = await call("run_terminal_command", command="seq 1 5000")
    assert "\n1\n" in out and out.rstrip().endswith("5000")
    assert "characters cut" in out


async def test_hosts_off_the_allowlist_and_option_like_hosts_are_refused():
    assert "not allowed" in await call("run_terminal_command", command="true", host="other")
    assert "not a valid SSH destination" in await call(
        "run_terminal_command", command="true", host="-oProxyCommand=touch /tmp/x"
    )


async def test_local_commands_can_be_turned_off():
    server.settings.local = False
    assert "local commands are turned off" in await call("run_terminal_command", command="true")


async def test_ssh_host_keeps_its_own_working_directory(fresh_state: Path):
    remote = fresh_state / "remote home"
    remote.mkdir()
    out = await call("run_terminal_command", command=f"cd '{remote}' && echo hi", host="box")
    assert "hi" in out and "exit: 0" in out
    assert server.cwds["box"] == str(remote.resolve())
    assert server.cwds[server.LOCAL] == str(fresh_state)  # local untouched
    out = await call("run_terminal_command", command="pwd", host="box")
    assert out.splitlines()[-1] == str(remote.resolve())


async def test_files_round_trip_over_ssh_with_awkward_names(fresh_state: Path):
    name = "dir with space/it's $HOME.txt"
    text = "line 1\n'quoted' $(not run)\n"
    assert "wrote" in await call("write_file", path=name, content=text, host="box")
    assert (fresh_state / name).read_text() == text  # the fake host's cwd is the test dir
    await call("write_file", path=name, content="more\n", host="box", append=True)
    out = await call("read_file", path=name, host="box")
    assert out.endswith(text + "more\n")
    out = await call("read_file", path=name, host="box", max_bytes=6)
    assert "(first 6 of" in out and out.endswith("line 1")


async def test_missing_file_is_a_plain_error():
    out = await call("read_file", path="nope 'x'.txt", host="box")
    assert out == "error: no such file: nope 'x'.txt"


async def test_list_hosts_and_remote_system_info():
    data = json.loads(await call("list_hosts"))
    assert [h["host"] for h in data["hosts"]] == ["local", "box"]
    info = json.loads(await call("get_system_info", host="box"))
    assert info["host"] == "box" and info["uname"]


async def test_read_only_tools_say_so():
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert set(tools) == {"list_hosts", "run_terminal_command", "read_file", "write_file", "get_system_info"}
    hints = {name: (t.annotations.model_dump(by_alias=True) if t.annotations else {}) for name, t in tools.items()}
    assert hints["read_file"]["readOnlyHint"] is True
    assert not hints["run_terminal_command"].get("readOnlyHint")


async def test_stdio_transport_keeps_stdout_clean(tmp_path: Path):
    """The old server printed to stdout before serving, which broke every stdio client."""
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "terminal_mcp.server"],
        env={**os.environ, "TERMINUS_SSH_HOSTS": ""},
        cwd=str(tmp_path),
    )
    async with Client(transport) as client:
        result = await client.call_tool("run_terminal_command", {"command": "echo over-stdio"})
    assert "over-stdio" in result.content[0].text


def test_binding_beyond_loopback_needs_explicit_consent():
    with pytest.raises(SystemExit):
        server.main(["--transport", "http", "--host", "0.0.0.0"])
