"""E2E test: verify opencode can connect to agenteum-net MCP and execute tools."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

SERVER_START_TIMEOUT = 10.0
MCP_READY_TIMEOUT = 10.0
OPENCODE_TIMEOUT = 120.0
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    """Return an ephemeral TCP port that is currently free."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _find_uv() -> str:
    """Return the uv executable path."""
    import shutil

    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not found in PATH")
    return uv


def _find_opencode() -> str:
    """Return the opencode executable path."""
    import shutil

    opencode = shutil.which("opencode")
    if opencode is None:
        pytest.skip("opencode not found in PATH")
    return opencode


def _ensure_port_free(port: int = 8765) -> None:
    """Terminate any process listening on *port*."""
    import shutil

    if sys.platform == "win32":
        netstat = shutil.which("netstat")
        if netstat is None:
            return
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    pid = parts[-1]
                    try:
                        int(pid)
                    except ValueError:
                        continue
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                    time.sleep(0.5)
    else:
        lsof = shutil.which("lsof")
        if lsof:
            result = subprocess.run(
                [lsof, "-ti", f":{port}"],
                capture_output=True,
                text=True,
            )
            for pid_str in result.stdout.strip().splitlines():
                try:
                    pid = int(pid_str)
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(0.5)
                except (ValueError, ProcessLookupError, PermissionError):
                    pass


def _wait_for_server(proc: subprocess.Popen, timeout: float = SERVER_START_TIMEOUT) -> None:
    """Wait until uvicorn logs 'Application startup complete'."""
    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            stdout = proc.stdout.read() if proc.stdout else ""
            stderr = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(
                f"Server exited early (code={proc.returncode}).\n"
                f"stdout: {stdout}\nstderr: {stderr}"
            )
        time.sleep(0.2)


def _run_opencode(cmd_args: list[str], timeout: float = OPENCODE_TIMEOUT) -> tuple[str, str, int]:
    """Run an opencode sub-command and return (stdout, stderr, returncode)."""
    full_cmd = [_find_opencode(), "--pure"] + cmd_args
    result = subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
    )
    return result.stdout, result.stderr, result.returncode


def _parse_opencode_json_events(raw: str) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON events from opencode --format json output."""
    events: list[dict[str, Any]] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _find_tool_use_event(
    events: list[dict[str, Any]],
    tool_name_substring: str,
) -> dict[str, Any] | None:
    """Find the first tool_use event whose tool name contains *tool_name_substring*."""
    for ev in events:
        if ev.get("type") == "tool_use":
            part = ev.get("part", {})
            tool = part.get("tool", "")
            if tool_name_substring in tool:
                return ev
    return None


@pytest.fixture(scope="module")
def server() -> subprocess.Popen:
    """Start agenteum-net server, yield the process, then terminate it."""
    uv = _find_uv()
    _ensure_port_free(8765)
    env = {
        **dict(subprocess.os.environ),
        "AGENTEUM_HOST": "127.0.0.1",
        "AGENTEUM_PORT": "8765",
        "AGENTEUM_ALLOW_REMOTE": "false",
    }
    proc = subprocess.Popen(
        [uv, "run", "agenteum-net"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    try:
        _wait_for_server(proc, timeout=SERVER_START_TIMEOUT)
        yield proc
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.fixture(scope="module", autouse=True)
def wait_after_server_start(server: subprocess.Popen) -> None:
    """Give the MCP server a moment to fully initialise before tests run."""
    time.sleep(1.0)


class TestOpencodeMcpConnection:
    """Verify opencode can discover and connect to agenteum-net MCP server."""

    def test_mcp_list_shows_agenteum_net_connected(self, server: subprocess.Popen) -> None:
        """opencode mcp list should report agenteum-net as connected."""
        stdout, stderr, rc = _run_opencode(["mcp", "list"])
        combined = stdout + stderr

        assert rc == 0, f"opencode mcp list exited with {rc}. Output:\n{combined}"
        assert "agenteum-net" in combined, (
            f"agenteum-net not found in MCP list. Output:\n{combined}"
        )
        assert "connected" in combined.lower(), (
            f"agenteum-net not marked connected. Output:\n{combined}"
        )


class TestOpencodeMcpTools:
    """Verify opencode non-interactive run can invoke agenteum-net tools."""

    def test_search_tool_is_called_via_agenteum_net(self, server: subprocess.Popen) -> None:
        """A prompt asking agenteum-net to search should trigger the search tool."""
        prompt = (
            "请通过 agenteum-net 搜索 'Python MCP server tutorial'，只返回工具调用结果"
        )
        stdout, stderr, rc = _run_opencode(
            ["run", "--format", "json", "--dangerously-skip-permissions", prompt]
        )

        # opencode may print ANSI codes to stderr; stdout should be pure JSON.
        events = _parse_opencode_json_events(stdout)

        assert events, f"No JSON events parsed from stdout. stdout:\n{stdout}\nstderr:\n{stderr}"

        tool_event = _find_tool_use_event(events, "search")
        assert tool_event is not None, (
            "No search tool_use event found. Events:\n"
            + json.dumps(events, indent=2, ensure_ascii=False)
        )

        part = tool_event.get("part", {})
        state = part.get("state", {})
        tool_input = state.get("input", {})

        # Verify the search query was passed through.
        assert tool_input.get("query") == "Python MCP server tutorial", (
            f"Unexpected search input: {tool_input}"
        )

    def test_fetch_tool_returns_content(self, server: subprocess.Popen) -> None:
        """A prompt asking agenteum-net to fetch a URL should return page content."""
        prompt = (
            "请通过 agenteum-net 抓取 https://example.com 的内容，并总结返回了什么"
        )
        stdout, stderr, rc = _run_opencode(
            ["run", "--format", "json", "--dangerously-skip-permissions", prompt]
        )

        events = _parse_opencode_json_events(stdout)
        assert events, f"No JSON events parsed from stdout. stdout:\n{stdout}\nstderr:\n{stderr}"

        tool_event = _find_tool_use_event(events, "fetch")
        assert tool_event is not None, (
            "No fetch tool_use event found. Events:\n"
            + json.dumps(events, indent=2, ensure_ascii=False)
        )

        part = tool_event.get("part", {})
        state = part.get("state", {})
        assert state.get("status") == "completed", (
            f"Fetch tool did not complete. State: {state}"
        )

        output = state.get("output", "")
        assert "Example Domain" in output or "example.com" in output.lower(), (
            f"Fetch output does not contain expected content. Output: {output[:500]}"
        )
